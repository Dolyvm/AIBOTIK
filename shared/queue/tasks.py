import logging
import os
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select, update

from shared.config import RUNPOD_FACE_SWAP_ENDPOINT_ID, RUNPOD_MANHWA_ENDPOINT_ID
from shared.database.exceptions import UsageLimitExceeded
from shared.database.repositories import ImageGenerationJobRepository
from shared.models import Chat, ImageGenerationJob, SubscriptionPlan, User
from shared.services.analytics import AnalyticsService
from shared.services.photo_generation import (
    PhotoGenerationCanceled,
    PhotoGenerationError,
    PhotoGenerationService,
    PhotoPromptBudgetError,
    PhotoProviderError,
    UnsupportedPhotoModelError,
)
from shared.services.runpod_job_registry import cancel_recorded_runpod_jobs
from shared.services.subscription import get_subscription_service

logger = logging.getLogger(__name__)


def _chat_photo_usage_type(character: dict | None) -> str:
    visual = (character or {}).get("visual") or {}
    if visual.get("custom_avatar"):
        return "avatar_generations"
    return "images_generated"


async def expire_subscriptions_task(ctx: dict) -> dict:
    """Cron: downgrade expired subscriptions to FREE and notify users."""
    get_session = ctx.get("get_session")
    if not get_session:
        logger.error("expire_subscriptions_task: no get_session in context")
        return {"status": "failed"}

    expired_user_ids = []
    async with get_session() as session:
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
            )
        )
        await session.commit()

    bot_token = os.getenv("BOT_TOKEN")
    if bot_token and expired_user_ids:
        bot = Bot(token=bot_token)
        try:
            for uid in expired_user_ids:
                try:
                    await bot.send_message(
                        uid,
                        "Ваша подписка истекла. Вы переведены на план Free.\n"
                        "Чтобы продлить, откройте приложение и выберите план.",
                    )
                except Exception as e:
                    logger.warning("Failed to notify user %s: %s", uid, e)
        finally:
            await bot.session.close()

    logger.info("expire_subscriptions: downgraded %s users", len(expired_user_ids))
    return {"status": "ok", "expired": len(expired_user_ids)}


async def generate_chat_image_task(ctx: dict, job_id: int) -> dict:
    get_session = ctx.get("get_session")
    if not get_session:
        logger.error("generate_chat_image_task: no get_session in context")
        return {"status": "failed", "job_id": job_id}

    service = PhotoGenerationService()
    sub_service = get_subscription_service()

    async with get_session() as session:
        job_repo = ImageGenerationJobRepository(session)
        job = await job_repo.get_by_id(job_id)
        if not job:
            logger.warning("generate_chat_image_task: job not found: job_id=%s", job_id)
            return {"status": "missing", "job_id": job_id}
        if job.status == "canceled":
            return {"status": "canceled", "job_id": job_id}
        if job.status not in {"queued", "running"}:
            return {"status": job.status, "job_id": job_id}

        if job.status == "queued":
            job = await job_repo.mark_running(job_id)
        if not job:
            return {"status": "missing", "job_id": job_id}

        payload = dict(job.request_payload or {})
        character = payload.get("character") or {}
        recent_messages = payload.get("recent_messages") or []
        chat_state = payload.get("chat_state") or {}
        usage_type = _chat_photo_usage_type(character)

        user = await session.get(User, job.user_id)
        chat = await session.get(Chat, job.chat_id)
        if not user or not chat:
            await job_repo.mark_failed(job_id, "context_missing", "Ошибка подготовки фото")
            return {"status": "failed", "job_id": job_id, "error": "context_missing"}

        async def ensure_job_active() -> None:
            fresh_job = await session.get(ImageGenerationJob, job_id, populate_existing=True)
            if not fresh_job or fresh_job.status == "canceled":
                raise PhotoGenerationCanceled("Image generation job was canceled")
            fresh_chat = await session.get(Chat, job.chat_id, populate_existing=True)
            if not fresh_chat:
                raise PhotoGenerationCanceled("Chat was deleted")

        async def record_runpod_job(
            provider: str,
            runpod_job_id: str,
            status_payload: dict,
        ) -> None:
            endpoint_id = {
                "runpod_facefusion": RUNPOD_FACE_SWAP_ENDPOINT_ID,
                "runpod_manhwa": RUNPOD_MANHWA_ENDPOINT_ID,
            }.get(provider)
            await job_repo.record_runpod_job(
                job_id,
                provider=provider,
                runpod_job_id=runpod_job_id,
                endpoint_id=endpoint_id,
                status_payload=status_payload,
            )

        try:
            await ensure_job_active()
            image = await service.generate_for_chat(
                session=session,
                user=user,
                chat_id=chat.id,
                character=character,
                recent_messages=recent_messages,
                chat_state=chat_state,
                before_save=ensure_job_active,
                on_runpod_job_created=record_runpod_job,
            )
            await ensure_job_active()
            await sub_service.increment_usage(user.telegram_id, usage_type, session)
            await AnalyticsService.track(
                session,
                user_id=user.telegram_id,
                event_type="image_generated",
                entity_type="chats",
                entity_id=str(chat.id),
                meta={
                    "character_id": character.get("id"),
                    "image_id": image.id,
                    "model_type": character.get("model_type"),
                    "job_id": job_id,
                    "usage_type": usage_type,
                },
            )
            await job_repo.mark_succeeded(job_id, image.id)
            return {"status": "succeeded", "job_id": job_id, "image_id": image.id}
        except PhotoGenerationCanceled:
            await session.rollback()
            fresh_job = await job_repo.get_by_id(job_id)
            await cancel_recorded_runpod_jobs(
                fresh_job.request_payload if fresh_job else payload,
                reason="local_job_canceled",
            )
            await job_repo.mark_canceled(job_id)
            return {"status": "canceled", "job_id": job_id}
        except asyncio.CancelledError:
            await session.rollback()
            fresh_job = await job_repo.get_by_id(job_id)
            await cancel_recorded_runpod_jobs(
                fresh_job.request_payload if fresh_job else payload,
                reason="arq_coroutine_cancelled",
            )
            await job_repo.mark_canceled(job_id, "Генерация отменена по таймауту")
            raise
        except UnsupportedPhotoModelError as e:
            await session.rollback()
            await job_repo.mark_failed(job_id, "unsupported_photo_model", str(e))
            return {"status": "failed", "job_id": job_id, "error": "unsupported_photo_model"}
        except PhotoPromptBudgetError as e:
            await session.rollback()
            await job_repo.mark_failed(job_id, "prompt_budget", str(e))
            return {"status": "failed", "job_id": job_id, "error": "prompt_budget"}
        except PhotoProviderError as e:
            await session.rollback()
            fresh_job = await job_repo.get_by_id(job_id)
            await cancel_recorded_runpod_jobs(
                fresh_job.request_payload if fresh_job else payload,
                reason="provider_failed",
            )
            logger.exception("Photo provider failed in worker: job_id=%s error=%s", job_id, e)
            await job_repo.mark_failed(job_id, "provider_failed", "Ошибка генерации фото")
            return {"status": "failed", "job_id": job_id, "error": "provider_failed"}
        except UsageLimitExceeded as e:
            await session.rollback()
            await job_repo.mark_failed(job_id, "usage_limit_exceeded", e.message)
            return {"status": "failed", "job_id": job_id, "error": "usage_limit_exceeded"}
        except PhotoGenerationError as e:
            await session.rollback()
            logger.exception("Photo generation failed in worker: job_id=%s error=%s", job_id, e)
            await job_repo.mark_failed(job_id, "generation_failed", "Ошибка подготовки фото")
            return {"status": "failed", "job_id": job_id, "error": "generation_failed"}
        except Exception as e:
            await session.rollback()
            fresh_job = await job_repo.get_by_id(job_id)
            await cancel_recorded_runpod_jobs(
                fresh_job.request_payload if fresh_job else payload,
                reason="unexpected_error",
            )
            logger.exception("Unexpected image generation worker failure: job_id=%s error=%s", job_id, e)
            await job_repo.mark_failed(job_id, "unexpected_error", "Ошибка генерации фото")
            return {"status": "failed", "job_id": job_id, "error": "unexpected_error"}


async def cancel_stale_image_jobs_task(ctx: dict) -> dict:
    """Watchdog: cancel local active image jobs that outlived the app budget."""
    get_session = ctx.get("get_session")
    if not get_session:
        logger.error("cancel_stale_image_jobs_task: no get_session in context")
        return {"status": "failed", "canceled": 0}

    max_age_seconds = int(os.getenv("IMAGE_JOB_WATCHDOG_SECONDS", "660"))
    cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
    canceled = 0

    async with get_session() as session:
        job_repo = ImageGenerationJobRepository(session)
        jobs = await job_repo.get_active_started_before(cutoff)
        for job in jobs:
            remote_canceled = await cancel_recorded_runpod_jobs(
                job.request_payload,
                reason="watchdog_stale_job",
            )
            await job_repo.mark_failed(
                job.id,
                "watchdog_stale_job",
                "Генерация остановлена по таймауту",
            )
            canceled += 1
            logger.warning(
                "Stale image job canceled: job_id=%s chat_id=%s remote_canceled=%s age_limit_seconds=%s",
                job.id,
                job.chat_id,
                remote_canceled,
                max_age_seconds,
            )

    return {"status": "ok", "canceled": canceled}
