import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4


sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, HTTPException, Query, Depends

from shared.models import User
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership
from shared.database import get_session
from shared.services.content_loader import get_character, get_world
from shared.services.redis_client import get_redis
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.subscription import get_subscription_service
from shared.services.image_provider import ImageProviderError, generate_image as provider_generate_image
from shared.services.model_types import validate_model_gender
from ..schemas.generate import GenerateRequest, ModelType, Prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

router = APIRouter(prefix="/api/image-gen", tags=["image-gen"])

@router.post("/build_prompt")
async def build_prompt_endpoint(data: Prompt, model_type: Optional[ModelType] = None, gender: str = "female"):
    return await data.build_prompt(model_type, gender=gender)

@router.post("/generate")
async def generate_image(data: GenerateRequest, user: User = Depends(get_current_user)):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_image_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["images"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "images", session)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("images", limit)

    nsfw_keywords = ["nsfw", "nude", "naked", "explicit", "erotic", "orgasm", "masturbat", "penetrat", "sex"]
    prompt_lower = data.prompt.lower()
    inferred_nsfw = sum(1 for kw in nsfw_keywords if kw in prompt_lower)
    nsfw_level = min(5, inferred_nsfw)

    try:
        image_url = await provider_generate_image(
            model_type=data.model_type.value,
            positive_prompt=data.prompt,
            negative_prompt=data.negative_prompt or "",
            allow_nsfw=data.allow_nsfw,
            nsfw_level=nsfw_level,
        )
    except ImageProviderError as e:
        logging.error(
            "Image provider failed in direct generate endpoint: code=%s provider=%s",
            e.code,
            e.provider,
        )
        raise HTTPException(status_code=502, detail=e.user_message)

    if image_url:
        async with get_session() as session:
            await sub_service.increment_usage(user.telegram_id, "images", session)
        return {"url": image_url}

    return {"error": "Failed to generate image"}

@router.post("/{chat_id}/generate")
async def gen(
    chat_id: int,
    outfit: str = Query(default="default_outfit", description="Ключ из wardrobe (casual, formal, gym, swimwear, sleepwear, underwear, nude)"),
    user: User = Depends(get_current_user)
):
                         
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_image_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["images"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "images", session)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("images", limit)

    chat = await verify_chat_ownership(chat_id, user)

    try:
        if chat.chat_type == "character":
            content = await get_character(chat.target_id)
            character, world = content, None
        else:
            content = await get_world(chat.target_id)
            character, world = None, content

        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error loading content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    model_type = content.get("model_type")
    char_gender = content.get("visual", {}).get("gender", "female")
    try:
        validate_model_gender(model_type, char_gender)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_id = str(uuid4())

    task_params = {
        "prepare_prompt": True,
        "chat_id": chat.id,
        "user_id": chat.user_id,
        "character_id": (character or {}).get("id"),
        "world_id": (world or {}).get("id"),
        "outfit": outfit,
        "allow_nsfw": content.get("is_nsfw", True),
    }

    redis = await get_redis()
    await redis.set(
        f"task:{task_id}",
        json.dumps({
            "status": "pending",
            "chat_id": chat.id,
            "user_id": chat.user_id,
            "created_at": datetime.utcnow().isoformat()
        }),
        ex=3600
    )

    try:
        from main import app
        arq_pool = getattr(app.state, "arq_pool", None)
        if arq_pool:
            await arq_pool.enqueue_job("generate_image_task", task_id, task_params)
            logging.info(f"Task {task_id} enqueued for chat {chat.id}")
        else:
            logging.warning("arq pool not configured, executing synchronously")
            from shared.queue.tasks import generate_image_task
            ctx = {"redis": redis, "get_session": get_session}
            result = await generate_image_task(ctx, task_id, task_params)
            if result.get("status") == "completed":
                async with get_session() as session:
                    await sub_service.increment_usage(user.telegram_id, "images", session)
                return result.get("result", {})
            raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to enqueue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start generation: {e}")

    async with get_session() as session:
        await sub_service.increment_usage(user.telegram_id, "images", session)

    response = {"task_id": task_id, "status": "pending", "chat_id": chat.id}
    logging.info(f"Returning response: {response}")
    return response
