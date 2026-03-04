import logging
import uuid

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.cache import get_cache
from shared.services.prompt_service import create_or_update_character_modifiers
from shared.constants import invalidate_character_modifiers_cache
from shared.models import User, Character
from shared.database import get_session
from auth.telegram_auth import get_current_user
from services.image_storage import save_avatar
from api.image_gen.schemas.generate import Prompt as ImagePrompt
from api.image_gen.services.generate import submit_anime, submit_real

from .cc_schemas import CreateCharacterRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/create_character")
async def create_character(
    data: CreateCharacterRequest,
    user: User = Depends(get_current_user),
):
    if not data.name or not data.description or not data.personality or not data.scenario or not data.first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")

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

        visual_data = {
            "model_type": data.model_type,
            "appearance": data.appearance or "",
            "body": data.visual_body or "",
            "face": data.visual_face or "",
            "default_outfit": data.visual_default_outfit or "",
            "style_tags": style_tags,
            "wardrobe": data.wardrobe,
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
            }
        ]
        for idx, alt_greeting in enumerate(data.alternate_greetings, start=1):
            if alt_greeting.strip():
                scenarios.append({
                    "index": idx,
                    "scenario": data.scenario,
                    "intro": alt_greeting.strip(),
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
            is_public=False,
            created_by_username_id=user.telegram_id,
            created_by_username=user.username,
        )

        db.add(new_character)
        await db.commit()

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

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"User {user.telegram_id} created character '{character_id}'")

    return {"character_id": character_id}


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

    try:
        if model_type == "real":
            image_url = await submit_real(prompt=pos, allow_nsfw=False, nsfw_level=0)
        else:
            image_url = await submit_anime(pos, neg)

        if not image_url:
            raise HTTPException(status_code=500, detail="Image generation failed")

        return {"url": image_url}
    except RateLimitExceeded:
        raise
    except Exception as e:
        logger.error(f"Avatar generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
