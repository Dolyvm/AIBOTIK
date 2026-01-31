import json
import logging
from datetime import datetime
from typing import Any

import replicate
import fal_client

logger = logging.getLogger(__name__)


async def _update_task_status(redis, task_id: str, status: str, **kwargs) -> None:
    """Update task status in Redis."""
    data = {
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
        **kwargs
    }
    await redis.set(f"task:{task_id}", json.dumps(data), ex=3600)


async def _submit_anime(positive_prompt: str, negative_prompt: str) -> str | None:
    """Generate anime-style image via Replicate."""
    model_version = "aisha-ai-official/wai-nsfw-illustrious-v12:0fc0fa9885b284901a6f9c0b4d67701fd7647d157b88371427d63f8089ce140e"

    result = await replicate.async_run(
        model_version,
        input={
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "vae": "default",
            "seed": -1,
            "cfg_scale": 5,
            "pag_scale": 5,
            "scheduler": "Euler a",
            "prepend_preprompt": False
        }
    )
    return result[0].url if result else None


async def _submit_real(prompt: str, allow_nsfw: bool, nsfw_level: int = 0) -> str | None:
    handler = await fal_client.submit_async(
        "fal-ai/z-image/turbo",
        arguments={
            "prompt": prompt,
            "enable_safety_checker": not allow_nsfw,
            "image_size": {"width": 1024, "height": 1024},
        }
    )

    result = await handler.get()
    logger.info(f"FAL result (nsfw_level={nsfw_level}): {result}")

    if result and "images" in result and result["images"]:
        return result["images"][0]["url"]
    return None


async def _download_and_save_image(provider_url: str, user_id: int) -> tuple[str, int, str] | None:
    """Download image and save locally."""
    import os
    import uuid
    import aiohttp
    import aiofiles
    from datetime import datetime
    from pathlib import Path

    IMAGES_STORAGE_PATH = os.getenv("IMAGES_STORAGE_PATH", "/app/generated_images")
    ALLOWED_CONTENT_TYPES = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }

    try:
        user_dir = Path(IMAGES_STORAGE_PATH) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]

        async with aiohttp.ClientSession() as session:
            async with session.get(provider_url, timeout=30) as response:
                if response.status != 200:
                    logger.error(f"Failed to download image: HTTP {response.status}")
                    return None

                content_type = response.headers.get("Content-Type", "image/png")
                content_type = content_type.split(";")[0].strip()

                extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")

                filename = f"{timestamp}_{unique_id}{extension}"
                local_path = f"{user_id}/{filename}"
                full_path = user_dir / filename

                content = await response.read()
                file_size = len(content)

                async with aiofiles.open(full_path, "wb") as f:
                    await f.write(content)

        logger.info(f"Image saved: {local_path} ({file_size} bytes)")
        return local_path, file_size, content_type

    except Exception as e:
        logger.error(f"Error saving image: {e}")
        return None


async def generate_image_task(ctx: dict[str, Any], task_id: str, params: dict) -> dict:
    """
    Background task for image generation.

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
    import os

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
        image_url = None
        if model_type == "anime":
            image_url = await _submit_anime(positive_prompt, negative_prompt)
        elif model_type == "real":
            image_url = await _submit_real(positive_prompt, allow_nsfw, nsfw_level)

        if not image_url:
            await _update_task_status(redis, task_id, "failed", error="Generation failed")
            return {"status": "failed", "error": "Generation failed"}

        # 3. Download and save locally
        await _update_task_status(redis, task_id, "downloading", chat_id=chat_id)

        local_path = None
        file_size = None
        content_type = None
        IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost/images")
        public_url = image_url

        save_result = await _download_and_save_image(image_url, user_id)
        if save_result:
            local_path, file_size, content_type = save_result
            public_url = f"{IMAGES_BASE_URL}/{local_path}"
            logger.info(f"Image saved locally: {local_path}")
        else:
            logger.warning(f"Failed to save image locally, using provider URL")

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
                        chat = await chat_repo.get(chat_id)
                        if chat:
                            current_meta = chat.state_meta or {}
                            await chat_repo.update_metrics(
                                chat_id,
                                {"state_meta": {"action": pose, "thought": current_meta.get("thought")}}
                            )

                logger.info(f"Image metadata saved to DB for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")
            # Continue - image was generated successfully

        # 5. Update final status
        result = {"url": public_url, "nsfw_level": nsfw_level}
        await _update_task_status(redis, task_id, "completed", result=result)

        logger.info(f"Task {task_id} completed successfully: {public_url}")
        return {"status": "completed", "result": result}

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        await _update_task_status(redis, task_id, "failed", error=str(e))
        return {"status": "failed", "error": str(e)}
