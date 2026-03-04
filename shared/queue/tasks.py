import json
import logging
import os
from datetime import datetime
from typing import Any

from shared.services.image_provider import generate_image
from shared.services.image_storage import download_and_save_image, save_avatar, ImageStorageError

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
    model_type = params["model_type"]
    positive_prompt = params["positive_prompt"]
    negative_prompt = params.get("negative_prompt", "")
    allow_nsfw = params.get("allow_nsfw", True)
    nsfw_level = params.get("nsfw_level", 0)
    pose = params.get("pose")

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
                        provider_url=image_url,
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
