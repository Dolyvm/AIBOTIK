import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from shared.services.image_provider import ImageProviderError, generate_image
from shared.services.image_storage import (
    ImageStorageError,
    download_and_save_image,
    local_image_to_data_url,
    persist_avatar_reference,
    save_avatar,
)
from shared.services.facefusion_provider import swap_face
from shared.services.identity_reference import analyze as analyze_identity_reference
from shared.services.content_loader import get_character, get_world
from shared.services.llm import LLMClient
from shared.services.model_types import validate_model_gender
from shared.config import (
    RUNPOD_FACEFUSION_PRESET,
    SCENE_ANALYZER_ENABLED,
    SCENE_ANALYZER_MODEL,
    SCENE_ANALYZER_TIMEOUT,
)

from shared.services.analytics import AnalyticsService
from shared.models import User, SubscriptionPlan, SubscriptionPayment
from shared.database.repositories import ChatRepository, MessageRepository
from shared.subscription_plans import PLAN_LIMITS
from shared.constants import get_heat_level

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


def _import_image_prompt_modules():
    try:
        from api.image_gen.schemas.generate import Prompt
        from api.image_gen.services.scene_analyzer import (
            SceneAnalyzer,
            has_explicit_nude_or_sex_context,
            infer_nsfw_level_from_history,
        )
    except ImportError:
        from backend.api.image_gen.schemas.generate import Prompt
        from backend.api.image_gen.services.scene_analyzer import (
            SceneAnalyzer,
            has_explicit_nude_or_sex_context,
            infer_nsfw_level_from_history,
        )

    return Prompt, SceneAnalyzer, has_explicit_nude_or_sex_context, infer_nsfw_level_from_history


def _default_body_profile(gender: str) -> dict:
    if gender == "male":
        return {
            "schema_version": 1,
            "body_type": "athletic",
            "height": "average",
            "outfit_preset": "casual",
        }
    return {
        "schema_version": 1,
        "body_type": "proportional",
        "height": "average",
        "breast_size": "medium",
        "butt_size": "rounded",
        "outfit_preset": "casual",
    }


async def _ensure_identity_reference(
    session,
    content: dict,
    character_id: str,
) -> dict:
    visual = content.get("visual") or {}
    identity_reference = visual.get("identity_reference") or {}
    if not visual.get("custom_avatar") or identity_reference.get("status") == "ready":
        return content

    from sqlalchemy import select
    from shared.models import Character
    from shared.services.cache import get_cache

    result = await session.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if not character:
        return content

    visual_data = dict(character.visual_data or {})
    avatar = visual_data.get("avatar") or content.get("avatar")
    if not avatar:
        raise ValueError("Custom avatar identity reference is missing source avatar")

    if not str(avatar).startswith("/images/"):
        avatar = await persist_avatar_reference(str(avatar), character_id)
        visual_data["avatar"] = avatar

    image_data_url = await local_image_to_data_url(str(avatar))
    identity = await analyze_identity_reference(image_data_url)
    identity_reference = {
        "status": "ready",
        "source_image": avatar,
        "provider": "openrouter",
        "model": identity["model"],
        "analyzed_at": identity["analyzed_at"],
        "identity_prompt": identity["identity_prompt"],
        "visible_traits": identity["visible_traits"],
        "avoid": identity["avoid"],
        "notes": identity["notes"],
        "consent_confirmed": True,
    }
    visual_data["model_type"] = "real"
    visual_data["custom_avatar"] = True
    visual_data["identity_reference"] = identity_reference
    visual_data.setdefault("body_profile", _default_body_profile(visual_data.get("gender", "female")))
    character.visual_data = visual_data
    await session.commit()

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    updated = dict(content)
    updated["model_type"] = "real"
    updated["avatar"] = visual_data.get("avatar", "")
    updated["visual"] = {
        k: v for k, v in visual_data.items()
        if k not in ["model_type", "appearance", "avatar", "example_dialogue"]
    }
    return updated


async def _prepare_chat_image_params(ctx: dict[str, Any], params: dict) -> dict:
    get_session = ctx.get("get_session")
    if not get_session:
        raise RuntimeError("Image task cannot prepare prompt without database session factory")

    (
        Prompt,
        SceneAnalyzer,
        has_explicit_nude_or_sex_context,
        infer_nsfw_level_from_history,
    ) = _import_image_prompt_modules()

    chat_id = params["chat_id"]
    requested_outfit = params.get("outfit") or "default_outfit"

    async with get_session() as session:
        chat_repo = ChatRepository(session)
        message_repo = MessageRepository(session)
        chat = await chat_repo.get_by_id(chat_id)
        if not chat:
            raise ValueError(f"Chat {chat_id} not found")
        messages = await message_repo.get_history(chat_id)

    content = await get_character(chat.target_id) if chat.chat_type == "character" else await get_world(chat.target_id)
    if not content:
        raise ValueError(f"Content {chat.target_id} not found")
    if chat.chat_type == "character" and content.get("visual", {}).get("custom_avatar", False):
        async with get_session() as session:
            content = await _ensure_identity_reference(session, content, chat.target_id)

    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in messages
    ]
    state_meta = chat.state_meta or {}
    heat_level = get_heat_level(chat)
    allow_nsfw = params.get("allow_nsfw", content.get("is_nsfw", True))
    early_non_explicit_context = (
        requested_outfit == "default_outfit"
        and len(history) <= 4
        and not has_explicit_nude_or_sex_context(history)
    )

    nsfw_level = 0
    outfit_key = requested_outfit
    environment = ""
    scene_reasoning = ""
    pose = ""
    scene_description = ""
    nsfw_tags = ""
    emotion = "neutral"

    if SCENE_ANALYZER_ENABLED and history:
        try:
            scene_llm = LLMClient(
                model=SCENE_ANALYZER_MODEL,
                provider={"sort": "latency"},
                reasoning={"enabled": False},
                timeout=SCENE_ANALYZER_TIMEOUT,
                max_retries=1,
            )
            analyzer = SceneAnalyzer(scene_llm)

            visual = content.get("visual", {})
            wardrobe = visual.get("wardrobe", {})
            if not isinstance(wardrobe, dict):
                wardrobe = {}
            available_outfits = {"default_outfit": visual.get("default_outfit", "")}
            for key, desc in wardrobe.items():
                available_outfits[key] = desc

            scene = await analyzer.analyze(
                history=history,
                character_name=content["name"],
                available_outfits=available_outfits,
                allow_nsfw=allow_nsfw,
                chat_id=chat_id,
                mood=chat.current_mood or "neutral",
                affinity=chat.affinity,
                arousal=chat.arousal,
                heat_level=heat_level,
                current_location=chat.current_location or "",
                model_type="anime" if content.get("model_type") == "manhwa" else content.get("model_type", "anime"),
                gender=content.get("visual", {}).get("gender", "female"),
            )

            nsfw_level = scene.nsfw_level
            outfit_key = scene.outfit_key
            pose = scene.pose
            environment = scene.location
            scene_reasoning = scene.reasoning
            emotion = scene.emotion
            scene_description = scene.scene_description
            nsfw_tags = scene.nsfw_tags

            logger.info(f"Scene analysis for image task {chat_id}: {scene_reasoning}")
        except Exception as e:
            logger.warning(f"Scene analysis failed for image task {chat_id}, using fallback: {e}")
            nsfw_level = infer_nsfw_level_from_history(
                history,
                heat_level=heat_level,
                arousal=chat.arousal,
                allow_nsfw=allow_nsfw,
            )
            if nsfw_level >= 4:
                outfit_key = "nude"
            elif nsfw_level >= 2:
                outfit_key = "underwear"
            environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")
    else:
        nsfw_level = infer_nsfw_level_from_history(
            history,
            heat_level=heat_level,
            arousal=chat.arousal,
            allow_nsfw=allow_nsfw,
        )
        if nsfw_level >= 4:
            outfit_key = "nude"
        elif nsfw_level >= 2:
            outfit_key = "underwear"
        environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")

    environment = chat.current_location or environment
    if allow_nsfw and early_non_explicit_context and nsfw_level > 1:
        logger.info(
            "Early non-explicit image context caps nsfw_level: %s -> 1",
            nsfw_level,
        )
        nsfw_level = 1
    if allow_nsfw and early_non_explicit_context and outfit_key != "default_outfit":
        logger.info(
            "Early non-explicit image context keeps default outfit: %s -> default_outfit",
            outfit_key,
        )
        outfit_key = "default_outfit"

    prompt = Prompt.from_character(
        character=content,
        outfit_key=outfit_key,
        nsfw_level=nsfw_level,
        environment=environment,
    )
    prompt.action = pose or state_meta.get("action", "")
    if emotion and emotion != "neutral":
        prompt.facial_expression = emotion
    if nsfw_level >= 4 and nsfw_tags:
        prompt.body_state = nsfw_tags

    logger.info(f"=== PROMPT COMPONENTS for image task chat {chat_id} ===")
    logger.info(f"  model_type={content.get('model_type')}")
    logger.info(f"  allow_nsfw={allow_nsfw}")
    logger.info(f"  heat_level={heat_level}")
    logger.info(f"  outfit_key={outfit_key}")
    logger.info(f"  clothing={prompt.clothing}")
    logger.info(f"  nsfw_level={nsfw_level}")
    logger.info(f"  body_profile_phrase={prompt.body_silhouette}")
    logger.info(
        "  visual_stage_reason=%s",
        "explicit nude/sexual context" if nsfw_level >= 4 else "clothed/sensual context",
    )
    logger.info(f"  scene_description={scene_description}")
    logger.info(f"  nsfw_tags={nsfw_tags}")
    logger.info(f"  emotion={emotion}")
    logger.info(f"  pose/action={prompt.action}")
    logger.info(f"  environment={prompt.environment}")
    logger.info(f"  character_base={prompt.character_base}")
    logger.info(f"  scene_reasoning={scene_reasoning}")
    logger.info("=== END COMPONENTS ===")

    model_type = content.get("model_type")
    char_gender = content.get("visual", {}).get("gender", "female")
    validate_model_gender(model_type, char_gender)
    positive_prompt, negative_prompt = await prompt.build_prompt(model_type, gender=char_gender)
    logger.info(
        "Built image prompt for chat %s: model_type=%s positive_chars=%s negative_chars=%s",
        chat_id,
        model_type,
        len(positive_prompt or ""),
        len(negative_prompt or ""),
    )

    seed_source = params.get("character_id") or params.get("world_id") or content.get("id") or content.get("name", "")
    seed = int(hashlib.md5(str(seed_source).encode()).hexdigest()[:8], 16) % (2**31)

    prepared = {
        **params,
        "character_id": params.get("character_id") or (content.get("id") if chat.chat_type == "character" else None),
        "world_id": params.get("world_id") or (content.get("id") if chat.chat_type == "world" else None),
        "model_type": model_type,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "allow_nsfw": allow_nsfw,
        "nsfw_level": nsfw_level,
        "pose": pose,
        "seed": seed,
    }
    visual = content.get("visual", {})
    identity_reference = visual.get("identity_reference") or {}
    if chat.chat_type == "character" and visual.get("custom_avatar") and identity_reference.get("status") == "ready":
        prepared["identity_pipeline"] = True
        prepared["identity_source_image"] = identity_reference.get("source_image") or content.get("avatar") or visual.get("avatar")
    prepared.pop("prepare_prompt", None)
    return prepared


async def generate_image_task(ctx: dict[str, Any], task_id: str, params: dict) -> dict:
    """
    Background task for chat image generation.

    params:
        prepare_prompt: bool (optional, build prompt from chat in worker)
        chat_id: int
        user_id: int
        character_id: Optional[int]
        world_id: Optional[int]
        model_type: "anime" | "real" | "manhwa"
        positive_prompt: str
        negative_prompt: str (optional, for anime)
        allow_nsfw: bool
        nsfw_level: int
        pose: str | None (optional)
    """
    redis = ctx["redis"]

    chat_id = params.get("chat_id")

    logger.info(f"Starting image generation task {task_id} for chat {chat_id}")

    try:
        if params.get("prepare_prompt"):
            await _update_task_status(redis, task_id, "analyzing", chat_id=chat_id, user_id=params.get("user_id"))
            params = await _prepare_chat_image_params(ctx, params)
            chat_id = params["chat_id"]

        user_id = params["user_id"]
        character_id = params.get("character_id")
        world_id = params.get("world_id")
        model_type = params["model_type"]
        positive_prompt = params["positive_prompt"]
        negative_prompt = params.get("negative_prompt", "")
        allow_nsfw = params.get("allow_nsfw", True)
        nsfw_level = params.get("nsfw_level", 0)
        pose = params.get("pose")
        seed = params.get("seed", -1)
        identity_pipeline = bool(params.get("identity_pipeline"))
        identity_source_image = params.get("identity_source_image")

        # 1. Update status to generating
        await _update_task_status(
            redis,
            task_id,
            "generating_target" if identity_pipeline else "generating",
            chat_id=chat_id,
            user_id=user_id,
        )

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
            await _update_task_status(redis, task_id, "failed", error="Generation failed", chat_id=chat_id, user_id=user_id)
            return {"status": "failed", "error": "Generation failed"}

        if identity_pipeline:
            if not identity_source_image:
                raise ImageProviderError(
                    "Identity source image is missing",
                    code="facefusion_swap_failed",
                    provider="runpod_facefusion",
                    user_message="Не удалось применить лицо к фото, попробуйте еще раз",
                    retryable=False,
                )
            await _update_task_status(redis, task_id, "face_swapping", chat_id=chat_id, user_id=user_id)
            source_image_data = await local_image_to_data_url(identity_source_image)
            image_url = await swap_face(source_image=source_image_data, target_image=image_url)

        # 3. Download and save locally
        await _update_task_status(redis, task_id, "downloading", chat_id=chat_id, user_id=user_id)

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
                        provider_url=None if identity_pipeline or image_url.startswith("data:image/") else image_url,
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
                            updated_meta = dict(current_meta)
                            updated_meta["action"] = pose
                            await chat_repo.update_metrics(
                                chat_id,
                                {"state_meta": updated_meta}
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
                            "nsfw_level": nsfw_level,
                            "identity_pipeline": identity_pipeline,
                            "face_swap_backend": "facefusion" if identity_pipeline else None,
                            "face_swap_preset": RUNPOD_FACEFUSION_PRESET if identity_pipeline else None,
                        }
                    )

                logger.info(f"Image metadata saved to DB for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")

        # 5. Update final status
        result = {"url": public_url, "nsfw_level": nsfw_level, "chat_id": chat_id}
        await _update_task_status(redis, task_id, "completed", chat_id=chat_id, user_id=user_id, result=result)

        logger.info(f"Task {task_id} completed successfully: {public_url}")
        return {"status": "completed", "result": result}

    except ImageProviderError as e:
        payload = e.to_task_payload()
        logger.error(
            "Task %s provider failed: code=%s provider=%s retryable=%s",
            task_id,
            payload.get("code"),
            payload.get("provider"),
            payload.get("retryable"),
        )
        await _update_task_status(
            redis,
            task_id,
            "failed",
            **payload,
            chat_id=chat_id,
            user_id=params.get("user_id"),
        )
        return {"status": "failed", **payload}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
        logger.error(f"Task {task_id} failed: {error_msg}")
        await _update_task_status(redis, task_id, "failed", error=error_msg, chat_id=chat_id, user_id=params.get("user_id"))
        return {"status": "failed", "error": error_msg}


async def generate_avatar_task(ctx: dict[str, Any], task_id: str, params: dict) -> dict:
    redis = ctx["redis"]

    model_type = params["model_type"]
    positive_prompt = params["positive_prompt"]
    negative_prompt = params.get("negative_prompt", "")
    allow_nsfw = params.get("allow_nsfw", False)
    user_id = params.get("user_id")
    owner_meta = {"user_id": user_id} if user_id is not None else {}

    logger.info(f"Starting avatar generation task {task_id}")

    try:
        await _update_task_status(redis, task_id, "generating", **owner_meta)

        image_url = await generate_image(
            model_type=model_type,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            allow_nsfw=allow_nsfw,
            nsfw_level=0,
        )

        if not image_url:
            await _update_task_status(redis, task_id, "failed", error="Generation failed", **owner_meta)
            return {"status": "failed", "error": "Generation failed"}

        result = {"url": image_url}
        await _update_task_status(redis, task_id, "completed", result=result, **owner_meta)

        logger.info(f"Avatar task {task_id} completed: {image_url}")
        return {"status": "completed", "result": result}

    except ImageProviderError as e:
        payload = e.to_task_payload()
        logger.error(
            "Avatar task %s provider failed: code=%s provider=%s retryable=%s",
            task_id,
            payload.get("code"),
            payload.get("provider"),
            payload.get("retryable"),
        )
        await _update_task_status(redis, task_id, "failed", **payload, **owner_meta)
        return {"status": "failed", **payload}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
        logger.error(f"Avatar task {task_id} failed: {error_msg}")
        await _update_task_status(redis, task_id, "failed", error=error_msg, **owner_meta)
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
