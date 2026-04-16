import json
import logging
import uuid
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from sqlalchemy import select

from shared.services.analytics import AnalyticsService
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.subscription import get_subscription_service
from shared.services.cache import get_cache
from shared.services.prompt_service import create_or_update_character_modifiers
from shared.services.image_storage import save_avatar, ALLOWED_CONTENT_TYPES
from shared.config import IMAGES_STORAGE_PATH
from shared.services.redis_client import get_redis
from shared.constants import invalidate_character_modifiers_cache
from shared.models import User, Character
from shared.database import get_session
from auth.telegram_auth import get_current_user
from api.image_gen.schemas.generate import Prompt as ImagePrompt

from .cc_schemas import CreateCharacterRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _clean_visual_field(value: str) -> str:
    """Strip trailing quotes and commas from user-pasted visual fields."""
    if not value:
        return value
    return value.strip().rstrip('",').rstrip('"').strip()


@router.post("/api/create_character")
async def create_character(
    data: CreateCharacterRequest,
    user: User = Depends(get_current_user),
):
    if not data.name or not data.description or not data.personality or not data.scenario or not data.first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "characters_created", session)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("characters_created", limit)

    character_id = f"custom_{user.telegram_id}_{uuid.uuid4().hex[:8]}"

    async with get_session() as db:
        result = await db.execute(select(Character).where(Character.id == character_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Character ID collision, please retry")

        style_tags = data.visual_style_tags or ""
        if not style_tags.strip():
            if data.model_type == "anime":
                style_tags = "anime style, cel shading, vibrant colors"
            else:
                style_tags = "soft natural lighting, film photography, warm tones"

        wardrobe = data.wardrobe or {}
        # Auto-add required wardrobe keys if missing
        if data.gender == "male":
            wardrobe.setdefault("nude", "nothing, showing his naked body")
            wardrobe.setdefault("underwear", "black boxer briefs")
        else:
            wardrobe.setdefault("nude", "nothing, showing her naked body")
            wardrobe.setdefault("underwear", "white bra, white panties")

        visual_data = {
            "model_type": data.model_type,
            "gender": data.gender,
            "appearance": _clean_visual_field(data.appearance or ""),
            "body": _clean_visual_field(data.visual_body or ""),
            "face": _clean_visual_field(data.visual_face or ""),
            "default_outfit": _clean_visual_field(data.visual_default_outfit or ""),
            "style_tags": style_tags,
            "wardrobe": wardrobe,
            "custom_avatar": data.custom_avatar,
        }

        if data.avatar_url:
            try:
                avatar_path = await save_avatar(data.avatar_url, character_id)
                visual_data["avatar"] = f"/images/{avatar_path}"
            except Exception as e:
                logger.warning(f"Failed to save avatar: {e}, using provider URL")
                visual_data["avatar"] = data.avatar_url

        tags = [tag.strip() for tag in data.tags if tag.strip()]

        scenarios = [
            {
                "index": 0,
                "scenario": data.scenario,
                "intro": data.first_message,
                "heat_level": data.heat_level,
            }
        ]
        for idx, alt_greeting in enumerate(data.alternate_greetings, start=1):
            if alt_greeting.strip():
                scenarios.append({
                    "index": idx,
                    "scenario": data.scenario,
                    "intro": alt_greeting.strip(),
                    "heat_level": data.heat_level,
                })

        new_character = Character(
            id=character_id,
            name=data.name,
            short_description=data.short_description or "",
            description=data.description,
            personality=data.personality,
            visual_data=visual_data,
            scenarios=scenarios,
            tags=tags,
            is_nsfw=True,
            is_public=data.is_public,
            is_verified=False,
            created_by_username_id=user.telegram_id,
            created_by_username=user.username,
        )

        db.add(new_character)
        await db.commit()

        await sub_service.increment_usage(user.telegram_id, "characters_created", db)

        modifiers = {1: "", 2: "", 3: "", 4: ""}
        await create_or_update_character_modifiers(
            character_id=character_id,
            character_name=data.name,
            is_nsfw=True,
            modifiers=modifiers,
            db=db,
        )
        await db.commit()
        await invalidate_character_modifiers_cache()

        await AnalyticsService.track(
            db,
            user_id=user.telegram_id,
            event_type="create_character",
            entity_type="characters",
            entity_id=str(character_id),
        )

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"User {user.telegram_id} created character '{character_id}'")

    return {"character_id": character_id}


@router.put("/api/characters/{character_id}")
async def update_character(
    character_id: str,
    data: CreateCharacterRequest,
    user: User = Depends(get_current_user),
):
    async with get_session() as db:
        result = await db.execute(select(Character).where(Character.id == character_id))
        character = result.scalar_one_or_none()

        if not character:
            raise HTTPException(status_code=404, detail="Character not found")

        if character.created_by_username_id != user.telegram_id:
            raise HTTPException(status_code=403, detail="You can only edit your own characters")

        if not data.name or not data.description or not data.personality or not data.scenario or not data.first_message:
            raise HTTPException(status_code=400, detail="All main fields are required")

        sub_service = get_subscription_service()
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "content_edits", db)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("content_edits", limit)
        await sub_service.increment_usage(user.telegram_id, "content_edits", db)

        style_tags = data.visual_style_tags or ""
        if not style_tags.strip():
            if data.model_type == "anime":
                style_tags = "anime style, cel shading, vibrant colors"
            else:
                style_tags = "soft natural lighting, film photography, warm tones"

        old_visual = character.visual_data or {}
        visual_data = {
            "model_type": data.model_type,
            "gender": data.gender,
            "appearance": _clean_visual_field(data.appearance or ""),
            "body": _clean_visual_field(data.visual_body or ""),
            "face": _clean_visual_field(data.visual_face or ""),
            "default_outfit": _clean_visual_field(data.visual_default_outfit or ""),
            "style_tags": style_tags,
            "wardrobe": data.wardrobe,
            "avatar": old_visual.get("avatar", ""),
            "custom_avatar": data.custom_avatar,
        }

        if data.avatar_url and data.avatar_url != old_visual.get("avatar", ""):
            try:
                avatar_path = await save_avatar(data.avatar_url, character_id)
                visual_data["avatar"] = f"/images/{avatar_path}"
            except Exception as e:
                logger.warning(f"Failed to save avatar: {e}, using provider URL")
                visual_data["avatar"] = data.avatar_url

        scenarios = [
            {
                "index": 0,
                "scenario": data.scenario,
                "intro": data.first_message,
                "heat_level": data.heat_level,
            }
        ]
        for idx, alt_greeting in enumerate(data.alternate_greetings, start=1):
            if alt_greeting.strip():
                scenarios.append({
                    "index": idx,
                    "scenario": data.scenario,
                    "intro": alt_greeting.strip(),
                    "heat_level": data.heat_level,
                })

        character.name = data.name
        character.short_description = data.short_description or ""
        character.description = data.description
        character.personality = data.personality
        character.visual_data = visual_data
        character.scenarios = scenarios
        character.tags = [tag.strip() for tag in data.tags if tag.strip()]
        character.is_public = data.is_public
        if not data.is_public:
            character.is_verified = False

        await db.commit()

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"User {user.telegram_id} updated character '{character_id}'")

    return {"success": True}


@router.post("/api/create_character/generate-avatar")
async def generate_avatar(
    data: dict,
    user: User = Depends(get_current_user),
):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_image_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["images"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    model_type = data.get("model_type", "anime")
    appearance = data.get("appearance", "")
    body = data.get("body", "")
    face = data.get("face", "")
    default_outfit = data.get("default_outfit", "")
    style_tags = data.get("style_tags", "")
    if not style_tags.strip():
        if model_type == "anime":
            style_tags = "anime style, cel shading, vibrant colors"
        else:
            style_tags = "soft natural lighting, film photography, warm tones"

    prompt = ImagePrompt(
        character_base=", ".join(filter(None, [appearance, body])),
        facial_expression=face,
        clothing=default_outfit,
        style=style_tags,
        nsfw_level=0,
    )

    pos, neg = await prompt.build_prompt(model_type)

    task_id = str(uuid4())
    task_params = {
        "model_type": model_type,
        "positive_prompt": pos,
        "negative_prompt": neg,
        "allow_nsfw": False,
    }

    redis = await get_redis()
    await redis.set(
        f"task:{task_id}",
        json.dumps({
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }),
        ex=3600
    )

    try:
        from main import app
        arq_pool = getattr(app.state, "arq_pool", None)
        if arq_pool:
            await arq_pool.enqueue_job("generate_avatar_task", task_id, task_params)
            logger.info(f"Avatar task {task_id} enqueued")
        else:
            logger.warning("arq pool not configured, executing avatar generation synchronously")
            from shared.queue.tasks import generate_avatar_task
            ctx = {"redis": redis, "get_session": get_session}
            result = await generate_avatar_task(ctx, task_id, task_params)
            if result.get("status") == "completed":
                return result.get("result", {})
            raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))
    except RateLimitExceeded:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Avatar generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    return {"task_id": task_id, "status": "pending"}


MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post("/api/create_character/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG and WebP images are allowed")

    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    from pathlib import Path
    import aiofiles

    ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    ext = ext_map.get(file.content_type, ".png")
    temp_name = f"temp_{uuid.uuid4().hex[:12]}{ext}"

    avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    full_path = avatars_dir / temp_name
    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)

    return {"url": f"/images/avatars/{temp_name}"}
