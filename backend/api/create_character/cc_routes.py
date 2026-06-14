import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select

from shared.services.analytics import AnalyticsService
from shared.services.subscription import get_subscription_service
from shared.services.cache import get_cache
from shared.services.prompt_service import create_or_update_character_modifiers
from shared.services.model_types import validate_model_gender
from shared.constants import invalidate_character_modifiers_cache
from shared.models import User, Character
from shared.database import get_session
from auth.telegram_auth import get_current_user

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
    model_type = data.model_type

    try:
        validate_model_gender(model_type, data.gender)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
            if model_type == "anime":
                style_tags = "anime style, cel shading, vibrant colors"
            elif model_type == "real":
                style_tags = "soft natural lighting, film photography, warm tones"
            else:
                style_tags = ""

        wardrobe = data.wardrobe or {}
        # Auto-add required wardrobe keys if missing
        if data.gender == "male":
            wardrobe.setdefault("nude", "nothing, showing his naked body")
            wardrobe.setdefault("underwear", "black boxer briefs")
        else:
            wardrobe.setdefault("nude", "nothing, showing her naked body")
            wardrobe.setdefault("underwear", "white bra, white panties")

        visual_data = {
            "model_type": model_type,
            "gender": data.gender,
            "appearance": _clean_visual_field(data.appearance or ""),
            "body": _clean_visual_field(data.visual_body or ""),
            "face": _clean_visual_field(data.visual_face or ""),
            "default_outfit": _clean_visual_field(data.visual_default_outfit or ""),
            "style_tags": style_tags,
            "wardrobe": wardrobe,
        }

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
            gender=data.gender,
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
        model_type = data.model_type

        try:
            validate_model_gender(model_type, data.gender)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        sub_service = get_subscription_service()
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "content_edits", db)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("content_edits", limit)

        style_tags = data.visual_style_tags or ""
        if not style_tags.strip():
            if model_type == "anime":
                style_tags = "anime style, cel shading, vibrant colors"
            elif model_type == "real":
                style_tags = "soft natural lighting, film photography, warm tones"
            else:
                style_tags = ""

        visual_data = {
            "model_type": model_type,
            "gender": data.gender,
            "appearance": _clean_visual_field(data.appearance or ""),
            "body": _clean_visual_field(data.visual_body or ""),
            "face": _clean_visual_field(data.visual_face or ""),
            "default_outfit": _clean_visual_field(data.visual_default_outfit or ""),
            "style_tags": style_tags,
            "wardrobe": data.wardrobe,
        }

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

        await sub_service.increment_usage(user.telegram_id, "content_edits", db)
        await db.commit()

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"User {user.telegram_id} updated character '{character_id}'")

    return {"success": True}
