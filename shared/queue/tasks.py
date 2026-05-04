import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from shared.services.image_provider import generate_image
from shared.services.image_storage import download_and_save_image, save_avatar, ImageStorageError

from shared.services.analytics import AnalyticsService
from shared.models import User, SubscriptionPlan, SubscriptionPayment
from shared.subscription_plans import PLAN_LIMITS

logger = logging.getLogger(__name__)

IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost/images")


async def _update_task_status(redis, task_id: str, status: str, **kwargs) -> None:
    """Update task status in Redis."""
    data = {
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
        **kwargs
    }
    await redis.set(f"task:{task_id}", json.dumps(data), ex=3600)


async def generate_image_task(ctx: dict[str, Any], task_id: str, params: dict) -> dict:
    """
    Background task for chat image generation.

    params:
        chat_id: int
        user_id: int
        character_id: Optional[int]
        world_id: Optional[int]
        model_type: "anime" | "real"
        positive_prompt: str
        negative_prompt: str (optional, for anime)
        allow_nsfw: bool
        nsfw_level: int
        pose: str | None (optional)
    """
    redis = ctx["redis"]

    chat_id = params["chat_id"]
    user_id = params["user_id"]
    character_id = params["character_id"]
    world_id = params["world_id"]
    model_type = params["model_type"]
    positive_prompt = params["positive_prompt"]
    negative_prompt = params.get("negative_prompt", "")
    allow_nsfw = params.get("allow_nsfw", True)
    nsfw_level = params.get("nsfw_level", 0)
    pose = params.get("pose")
    seed = params.get("seed", -1)

    logger.info(f"Starting image generation task {task_id} for chat {chat_id}")

    try:
        # 1. Update status to generating
        await _update_task_status(redis, task_id, "generating", chat_id=chat_id)

        # 2. Generate image
        image_url = await generate_image(
            model_type=model_type,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            allow_nsfw=allow_nsfw,
            nsfw_level=nsfw_level,
            seed=seed,
        )

        if not image_url:
            await _update_task_status(redis, task_id, "failed", error="Generation failed")
            return {"status": "failed", "error": "Generation failed"}

        # 3. Download and save locally
        await _update_task_status(redis, task_id, "downloading", chat_id=chat_id)

        local_path = None
        file_size = None
        content_type = None
        public_url = image_url

        try:
            local_path, file_size, content_type = await download_and_save_image(image_url, user_id)
            public_url = f"{IMAGES_BASE_URL}/{local_path}"
            logger.info(f"Image saved locally: {local_path}")
        except ImageStorageError:
            logger.warning("Failed to save image locally, using provider URL")

        # 4. Save to database
        try:
            get_session = ctx.get("get_session")
            if get_session:
                from shared.database.repositories import GeneratedImageRepository, ChatRepository

                async with get_session() as session:
                    image_repo = GeneratedImageRepository(session)
                    await image_repo.save(
                        user_id=user_id,
                        chat_id=chat_id,
                        prompt=positive_prompt,
                        provider_url=None if image_url.startswith("data:image/") else image_url,
                        local_path=local_path,
                        file_size=file_size,
                        content_type=content_type,
                        nsfw_level=nsfw_level
                    )

                    if pose:
                        chat_repo = ChatRepository(session)
                        chat = await chat_repo.get_by_id(chat_id)
                        if chat:
                            current_meta = chat.state_meta or {}
                            await chat_repo.update_metrics(
                                chat_id,
                                {"state_meta": {"action": pose, "thought": current_meta.get("thought")}}
                            )
                    await AnalyticsService.track(
                        session,
                        user_id=user_id,
                        event_type="image_generated",
                        entity_type="chats",
                        entity_id=str(chat_id),
                        meta={
                            "character_id": str(character_id) if character_id else None,
                            "model_type": model_type,
                            "world_id": str(world_id) if world_id else None,
                            "nsfw_level": nsfw_level
                        }
                    )

                logger.info(f"Image metadata saved to DB for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")

        # 5. Update final status
        result = {"url": public_url, "nsfw_level": nsfw_level}
        await _update_task_status(redis, task_id, "completed", result=result)

        logger.info(f"Task {task_id} completed successfully: {public_url}")
        return {"status": "completed", "result": result}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
        logger.error(f"Task {task_id} failed: {error_msg}")
        await _update_task_status(redis, task_id, "failed", error=error_msg)
        return {"status": "failed", "error": error_msg}


async def generate_avatar_task(ctx: dict[str, Any], task_id: str, params: dict) -> dict:
    redis = ctx["redis"]

    model_type = params["model_type"]
    positive_prompt = params["positive_prompt"]
    negative_prompt = params.get("negative_prompt", "")
    allow_nsfw = params.get("allow_nsfw", False)

    logger.info(f"Starting avatar generation task {task_id}")

    try:
        await _update_task_status(redis, task_id, "generating")

        image_url = await generate_image(
            model_type=model_type,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            allow_nsfw=allow_nsfw,
            nsfw_level=0,
        )

        if not image_url:
            await _update_task_status(redis, task_id, "failed", error="Generation failed")
            return {"status": "failed", "error": "Generation failed"}

        result = {"url": image_url}
        await _update_task_status(redis, task_id, "completed", result=result)

        logger.info(f"Avatar task {task_id} completed: {image_url}")
        return {"status": "completed", "result": result}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
        logger.error(f"Avatar task {task_id} failed: {error_msg}")
        await _update_task_status(redis, task_id, "failed", error=error_msg)
        return {"status": "failed", "error": error_msg}


async def expire_subscriptions_task(ctx: dict[str, Any]) -> dict:
    """Cron: даунгрейд истёкших подписок до FREE, отправка уведомлений."""
    from sqlalchemy import select, update
    from aiogram import Bot

    get_session = ctx.get("get_session")
    if not get_session:
        logger.error("expire_subscriptions_task: no get_session in context")
        return {"status": "failed"}

    expired_user_ids = []
    async with get_session() as session:
        # Найти всех с истёкшими подписками
        result = await session.execute(
            select(User.telegram_id, User.subscription_plan).where(
                User.subscription_end_date < datetime.utcnow(),
                User.subscription_plan != SubscriptionPlan.FREE,
            )
        )
        expired_users = result.all()
        expired_user_ids = [row[0] for row in expired_users]

        if not expired_user_ids:
            logger.info("expire_subscriptions: no expired subscriptions found")
            return {"status": "ok", "expired": 0}

        # Батч-обновление
        await session.execute(
            update(User)
            .where(
                User.subscription_end_date < datetime.utcnow(),
                User.subscription_plan != SubscriptionPlan.FREE,
            )
            .values(
                subscription_plan=SubscriptionPlan.FREE,
                is_subscribed=False,
                subscription_end_date=None,
                subscription_start_date=None,
                subscription_auto_renew=False,
            )
        )
        await session.commit()

    # Уведомления через бота
    bot_token = os.getenv("BOT_TOKEN")
    if bot_token and expired_user_ids:
        bot = Bot(token=bot_token)
        try:
            for uid in expired_user_ids:
                try:
                    await bot.send_message(
                        uid,
                        "⏰ Ваша подписка истекла. Вы переведены на план Free.\n"
                        "Чтобы продлить, откройте приложение и выберите план.",
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify user {uid}: {e}")
        finally:
            await bot.session.close()

    logger.info(f"expire_subscriptions: downgraded {len(expired_user_ids)} users")
    return {"status": "ok", "expired": len(expired_user_ids)}


async def auto_renew_subscriptions_task(ctx: dict[str, Any]) -> dict:
    """Cron: отправка invoice пользователям с auto_renew=True, подписка истекает в ближайшие 24ч."""
    from sqlalchemy import select
    from aiogram import Bot
    from aiogram.types import LabeledPrice

    get_session = ctx.get("get_session")
    if not get_session:
        logger.error("auto_renew_task: no get_session in context")
        return {"status": "failed"}

    now = datetime.utcnow()
    threshold = now + timedelta(hours=24)

    async with get_session() as session:
        result = await session.execute(
            select(User).where(
                User.subscription_auto_renew == True,
                User.subscription_plan != SubscriptionPlan.FREE,
                User.subscription_end_date != None,
                User.subscription_end_date <= threshold,
                User.subscription_end_date > now,
            )
        )
        users = result.scalars().all()

        if not users:
            logger.info("auto_renew: no users to renew")
            return {"status": "ok", "sent": 0}

        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logger.error("auto_renew: BOT_TOKEN not set")
            return {"status": "failed"}

        from shared.database.repositories.subscription import SubscriptionRepository

        bot = Bot(token=bot_token)
        sent = 0
        try:
            for user in users:
                plan = user.subscription_plan
                try:
                    plan_config = PLAN_LIMITS[plan]
                except KeyError:
                    logger.error(f"auto_renew: unknown plan {plan} for user {user.telegram_id}")
                    continue
                price = plan_config["price_stars"]

                # Проверить существующие pending платежи — не дублировать invoice
                existing = await session.execute(
                    select(SubscriptionPayment).where(
                        SubscriptionPayment.user_id == user.telegram_id,
                        SubscriptionPayment.plan == plan,
                        SubscriptionPayment.status == "pending",
                    )
                )
                if existing.scalar_one_or_none():
                    logger.info(f"auto_renew: pending payment already exists for user {user.telegram_id}")
                    continue

                repo = SubscriptionRepository(session)
                payment = await repo.create_payment(
                    user_id=user.telegram_id,
                    plan=plan,
                    amount_stars=price,
                    amount_rub=plan_config["price_rub"],
                )

                try:
                    await bot.send_invoice(
                        chat_id=user.telegram_id,
                        title=f"Автопродление: {plan_config['display_name']}",
                        description=f"Автопродление подписки на {plan_config.get('duration_days', 30)} дней",
                        payload=str(payment.id),
                        currency="XTR",
                        prices=[LabeledPrice(label="Подписка", amount=price)],
                    )
                    sent += 1
                except Exception as e:
                    logger.warning(f"Failed to send renewal invoice to {user.telegram_id}: {e}")
        finally:
            await bot.session.close()

    logger.info(f"auto_renew: sent {sent} invoices")
    return {"status": "ok", "sent": sent}
