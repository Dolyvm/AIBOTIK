import json
import logging
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from sqlalchemy import select

from shared.services.analytics import AnalyticsService
from shared.services.subscription import get_subscription_service
from shared.services.cache import get_cache
from shared.services.identity_reference import IdentityReferenceError, analyze as analyze_identity_reference
from shared.services.image_storage import (
    ALLOWED_CONTENT_TYPES,
    local_image_to_data_url,
    persist_avatar_reference,
)
from shared.services.photo_generation import (
    apply_default_wardrobe,
    default_style_tags_for_model,
    PhotoGenerationError,
    PhotoGenerationService,
    PhotoPromptBudgetError,
    PhotoProviderError,
    UnsupportedPhotoModelError,
)
from shared.services.prompt_service import create_or_update_character_modifiers
from shared.services.model_types import validate_model_gender
from shared.constants import invalidate_character_modifiers_cache
from shared.models import User, Character
from shared.database import get_session
from shared.database.exceptions import UsageLimitExceeded
from auth.telegram_auth import get_current_user

from shared.config import IMAGES_STORAGE_PATH

from .cc_schemas import BodyProfile, CreateCharacterAvatarRequest, CreateCharacterRequest

logger = logging.getLogger(__name__)
root_logger = logging.getLogger()

router = APIRouter()
photo_generation_service = PhotoGenerationService()

AVATAR_DRAFT_TTL_SECONDS = 24 * 60 * 60
FREE_AVATAR_GENERATIONS_PER_DRAFT = 2
CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")


def _clean_visual_field(value: str) -> str:
    """Strip trailing quotes and commas from user-pasted visual fields."""
    if not value:
        return value
    return value.strip().rstrip('",').rstrip('"').strip()


def _default_body_profile(gender: str) -> dict[str, Any]:
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


def _normalize_body_profile(profile: BodyProfile | None, gender: str) -> dict[str, Any]:
    result = _default_body_profile(gender)
    if profile:
        result.update(profile.model_dump(exclude_none=True))
    result["schema_version"] = 1
    if gender == "male":
        result.pop("breast_size", None)
        result.pop("butt_size", None)
    return result


async def _build_custom_identity_metadata(
    *,
    avatar_url: str,
    character_id: str,
    gender: str,
    body_profile: BodyProfile | None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    avatar_path = await persist_avatar_reference(avatar_url, character_id)
    image_data_url = await local_image_to_data_url(avatar_path)
    identity = await analyze_identity_reference(image_data_url)
    identity_reference = {
        "status": "ready",
        "source_image": avatar_path,
        "provider": "openrouter",
        "model": identity["model"],
        "analyzed_at": identity["analyzed_at"],
        "identity_prompt": identity["identity_prompt"],
        "visible_traits": identity["visible_traits"],
        "avoid": identity["avoid"],
        "notes": identity["notes"],
        "consent_confirmed": True,
    }
    return avatar_path, identity_reference, _normalize_body_profile(body_profile, gender)


def _avatar_draft_key(user_id: int) -> str:
    return f"character_create_avatar:{user_id}"


def _avatar_draft_lock(user_id: int) -> str:
    return f"character_create_avatar:{user_id}"


async def _build_visual_data(data: CreateCharacterRequest | CreateCharacterAvatarRequest) -> dict[str, Any]:
    model_type = data.model_type
    wardrobe = await apply_default_wardrobe(data.wardrobe or {}, data.gender)

    visual_data = {
        "model_type": model_type,
        "gender": data.gender,
        "appearance": _clean_visual_field(data.appearance or ""),
        "body": _clean_visual_field(data.visual_body or ""),
        "face": _clean_visual_field(data.visual_face or ""),
        "default_outfit": _clean_visual_field(data.visual_default_outfit or ""),
        "style_tags": await default_style_tags_for_model(model_type, data.visual_style_tags),
        "wardrobe": wardrobe,
    }
    if getattr(data, "tag_overrides", None):
        visual_data["tag_overrides"] = dict(data.tag_overrides or {})
    return visual_data


def _appearance_hash(name: str, visual_data: Mapping[str, Any]) -> str:
    payload = {
        "name": (name or "").strip(),
        "visual_data": visual_data,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_avatar_cache():
    cache = get_cache()
    if not cache or not getattr(cache, "redis", None):
        raise HTTPException(status_code=503, detail="Генерация аватарки временно недоступна")
    return cache


async def _load_avatar_draft(cache, user_id: int) -> dict[str, Any] | None:
    raw = await cache.redis.get(_avatar_draft_key(user_id))
    if not raw:
        return None
    try:
        draft = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.warning("Invalid avatar draft JSON: user_id=%s", user_id)
        return None
    if not isinstance(draft, dict):
        return None
    return draft


async def _save_avatar_draft(cache, user_id: int, draft: Mapping[str, Any]) -> None:
    await cache.redis.setex(
        _avatar_draft_key(user_id),
        AVATAR_DRAFT_TTL_SECONDS,
        json.dumps(dict(draft), ensure_ascii=False),
    )


async def _delete_avatar_draft(cache, user_id: int) -> None:
    await cache.redis.delete(_avatar_draft_key(user_id))


def _validate_visual_for_avatar(data: CreateCharacterAvatarRequest) -> None:
    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="Введите имя персонажа")
    if not data.appearance or not data.appearance.strip():
        raise HTTPException(status_code=400, detail="Заполните поле внешности")
    try:
        validate_model_gender(data.model_type, data.gender)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    visual_fields = [
        data.appearance,
        data.visual_body,
        data.visual_face,
        data.visual_default_outfit,
        data.visual_style_tags,
        *(data.wardrobe or {}).values(),
    ]
    if any(field and CYRILLIC_RE.search(field) for field in visual_fields):
        raise HTTPException(status_code=400, detail="Поля внешности должны быть на английском")


async def _ensure_avatar_cache_available(cache) -> None:
    try:
        await cache.redis.ping()
    except Exception as e:
        logger.error("Avatar draft Redis unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Генерация аватарки временно недоступна")


@router.post("/api/create_character/avatar")
async def generate_character_avatar(
    data: CreateCharacterAvatarRequest,
    user: User = Depends(get_current_user),
):
    _validate_visual_for_avatar(data)
    cache = _require_avatar_cache()
    await _ensure_avatar_cache_available(cache)

    lock_name = _avatar_draft_lock(user.telegram_id)
    lock_acquired = await cache.acquire_lock(lock_name, ttl=600)
    if not lock_acquired:
        raise HTTPException(status_code=409, detail="Аватарка уже генерируется")

    try:
        sub_service = get_subscription_service()
        async with get_session() as session:
            allowed, remaining, limit = await sub_service.check_usage_allowed(
                user.telegram_id,
                "characters_created",
                session,
            )
            if not allowed:
                raise UsageLimitExceeded("characters_created", limit)

        visual_data = await _build_visual_data(data)
        current_hash = _appearance_hash(data.name, visual_data)

        try:
            draft = await _load_avatar_draft(cache, user.telegram_id)
        except Exception as e:
            logger.error("Failed to load avatar draft: user_id=%s error=%s", user.telegram_id, e)
            raise HTTPException(status_code=503, detail="Генерация аватарки временно недоступна")

        if not draft:
            draft = {
                "draft_id": uuid.uuid4().hex,
                "avatar_urls": [],
                "selected_avatar_url": "",
                "free_generations_used": 0,
                "paid_generations_used": 0,
                "appearance_hash": current_hash,
            }
        elif draft.get("appearance_hash") != current_hash:
            draft = {
                **draft,
                "avatar_urls": [],
                "selected_avatar_url": "",
                "appearance_hash": current_hash,
            }

        free_used = int(draft.get("free_generations_used") or 0)
        is_paid_generation = free_used >= FREE_AVATAR_GENERATIONS_PER_DRAFT
        if is_paid_generation:
            async with get_session() as session:
                allowed, remaining, limit = await sub_service.check_usage_allowed(
                    user.telegram_id,
                    "images_generated",
                    session,
                )
                if not allowed:
                    raise UsageLimitExceeded("images_generated", limit)

        try:
            avatar_url = await photo_generation_service.generate_avatar(
                {
                    "id": f"draft_{user.telegram_id}_{draft['draft_id']}",
                    "name": data.name,
                    "model_type": data.model_type,
                    "is_nsfw": True,
                    "visual_data": visual_data,
                }
            )
        except UnsupportedPhotoModelError as e:
            logger.exception(
                "Character avatar preview unsupported model: user_id=%s model_type=%s error=%s",
                user.telegram_id,
                data.model_type,
                e,
            )
            root_logger.exception("Character avatar preview unsupported model")
            raise HTTPException(
                status_code=400,
                detail={"code": "unsupported_photo_model", "message": str(e)},
            )
        except PhotoPromptBudgetError as e:
            logger.exception(
                "Character avatar preview prompt budget failed: user_id=%s model_type=%s gender=%s error=%s",
                user.telegram_id,
                data.model_type,
                data.gender,
                e,
            )
            root_logger.exception("Character avatar preview prompt budget failed")
            raise HTTPException(
                status_code=400,
                detail={"code": "prompt_budget", "message": "Слишком длинное описание внешности для аватарки"},
            )
        except PhotoProviderError as e:
            logger.exception(
                "Character avatar preview provider failed: user_id=%s model_type=%s gender=%s error=%s",
                user.telegram_id,
                data.model_type,
                data.gender,
                e,
            )
            root_logger.exception("Character avatar preview provider failed")
            raise HTTPException(
                status_code=503,
                detail={"code": "provider_failed", "message": "Провайдер генерации фото временно недоступен"},
            )
        except PhotoGenerationError as e:
            logger.exception(
                "Character avatar preview generation failed: user_id=%s model_type=%s gender=%s error=%s",
                user.telegram_id,
                data.model_type,
                data.gender,
                e,
            )
            root_logger.exception("Character avatar preview generation failed")
            raise HTTPException(
                status_code=500,
                detail={"code": "generation_failed", "message": str(e) or "Ошибка генерации аватарки"},
            )
        except Exception as e:
            logger.exception(
                "Character avatar preview unexpected failure: user_id=%s model_type=%s gender=%s error=%s",
                user.telegram_id,
                data.model_type,
                data.gender,
                e,
            )
            root_logger.exception("Character avatar preview unexpected failure")
            raise HTTPException(
                status_code=500,
                detail={"code": "unexpected_avatar_generation_error", "message": str(e) or "Ошибка генерации аватарки"},
            )

        previous_draft = dict(draft)
        avatar_urls = list(draft.get("avatar_urls") or [])
        avatar_urls.append(avatar_url)
        draft = {
            **draft,
            "avatar_urls": avatar_urls,
            "selected_avatar_url": avatar_url,
        }
        if is_paid_generation:
            draft["paid_generations_used"] = int(draft.get("paid_generations_used") or 0) + 1
        else:
            draft["free_generations_used"] = free_used + 1

        try:
            await _save_avatar_draft(cache, user.telegram_id, draft)
        except Exception as e:
            logger.error("Failed to save avatar draft: user_id=%s error=%s", user.telegram_id, e)
            raise HTTPException(status_code=503, detail="Генерация аватарки временно недоступна")

        if is_paid_generation:
            try:
                async with get_session() as session:
                    await sub_service.increment_usage(user.telegram_id, "images_generated", session)
            except Exception:
                try:
                    await _save_avatar_draft(cache, user.telegram_id, previous_draft)
                except Exception:
                    logger.exception("Failed to rollback paid avatar draft: user_id=%s", user.telegram_id)
                raise

        return {
            "draft_id": draft["draft_id"],
            "avatar_url": avatar_url,
            "avatar_urls": avatar_urls,
            "selected_avatar_url": avatar_url,
            "free_generations_used": draft["free_generations_used"],
            "paid_generations_used": draft["paid_generations_used"],
            "free_generations_remaining": max(
                0,
                FREE_AVATAR_GENERATIONS_PER_DRAFT - int(draft["free_generations_used"]),
            ),
            "charged": is_paid_generation,
        }
    finally:
        await cache.release_lock(lock_name)


MAX_AVATAR_UPLOAD_SIZE = 5 * 1024 * 1024
ALLOWED_AVATAR_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post("/api/create_character/upload-avatar")
async def upload_character_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_AVATAR_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail="Можно загрузить только JPEG, PNG или WebP")

    content = await file.read()
    if len(content) > MAX_AVATAR_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Файл должен быть меньше 5MB")

    import aiofiles

    extension = ALLOWED_CONTENT_TYPES.get(file.content_type, ".png")
    filename = f"upload_{user.telegram_id}_{uuid.uuid4().hex[:12]}{extension}"
    avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    full_path = avatars_dir / filename
    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)

    return {"url": f"/images/avatars/{filename}"}


@router.post("/api/create_character")
async def create_character(
    data: CreateCharacterRequest,
    user: User = Depends(get_current_user),
):
    if not data.name or not data.description or not data.personality or not data.scenario or not data.first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")
    model_type = "real" if data.custom_avatar else data.model_type
    if data.custom_avatar:
        if not data.selected_avatar_url:
            raise HTTPException(status_code=400, detail="Загрузите фото")
        if not data.identity_consent_confirmed:
            raise HTTPException(status_code=400, detail="Подтвердите согласие на использование фото")

    try:
        validate_model_gender(model_type, data.gender)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not data.custom_avatar and (not data.avatar_draft_id or not data.selected_avatar_url):
        raise HTTPException(status_code=400, detail="Сгенерируйте аватарку перед созданием персонажа")

    visual_data = await _build_visual_data(data)
    visual_data["model_type"] = model_type
    avatar_url = data.selected_avatar_url.strip()
    cache = get_cache()
    if data.custom_avatar:
        visual_data["custom_avatar"] = True
        visual_data["style_tags"] = await default_style_tags_for_model("real", data.visual_style_tags)
    else:
        current_hash = _appearance_hash(data.name, visual_data)
        cache = _require_avatar_cache()
        await _ensure_avatar_cache_available(cache)
        try:
            draft = await _load_avatar_draft(cache, user.telegram_id)
        except Exception as e:
            logger.error("Failed to load avatar draft before character create: user_id=%s error=%s", user.telegram_id, e)
            raise HTTPException(status_code=503, detail="Генерация аватарки временно недоступна")

        if not draft or draft.get("draft_id") != data.avatar_draft_id:
            raise HTTPException(status_code=400, detail="Черновик аватарки не найден")
        if draft.get("appearance_hash") != current_hash:
            raise HTTPException(status_code=400, detail="Аватарка устарела, сгенерируйте новую")
        if avatar_url not in (draft.get("avatar_urls") or []):
            raise HTTPException(status_code=400, detail="Выбранная аватарка не найдена в черновике")

        visual_data["avatar"] = avatar_url

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "characters_created", session)
        if not allowed:
            raise UsageLimitExceeded("characters_created", limit)

    character_id = f"custom_{user.telegram_id}_{uuid.uuid4().hex[:8]}"

    if data.custom_avatar:
        try:
            avatar_path, identity_reference, body_profile = await _build_custom_identity_metadata(
                avatar_url=avatar_url,
                character_id=character_id,
                gender=data.gender,
                body_profile=data.body_profile,
            )
            visual_data["avatar"] = avatar_path
            visual_data["identity_reference"] = identity_reference
            visual_data["body_profile"] = body_profile
            visual_data["appearance"] = _clean_visual_field(
                data.appearance or identity_reference.get("identity_prompt", "")
            )
        except IdentityReferenceError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            logger.warning("Failed to prepare custom identity avatar: %s", e)
            raise HTTPException(status_code=400, detail="Не удалось обработать фото")

    async with get_session() as db:
        result = await db.execute(select(Character).where(Character.id == character_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Character ID collision, please retry")

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

        if not data.custom_avatar and cache:
            try:
                await _delete_avatar_draft(cache, user.telegram_id)
            except Exception as e:
                logger.exception(
                    "Failed to delete avatar draft after character create: character_id=%s user_id=%s error=%s",
                    character_id,
                    user.telegram_id,
                    e,
                )

    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"User {user.telegram_id} created character '{character_id}'")

    return {"character_id": character_id, "avatar": avatar_url}


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
        old_visual = character.visual_data or {}
        custom_avatar = bool(data.custom_avatar or old_visual.get("custom_avatar"))
        model_type = "real" if custom_avatar else data.model_type

        try:
            validate_model_gender(model_type, data.gender)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        sub_service = get_subscription_service()
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "content_edits", db)
        if not allowed:
            raise UsageLimitExceeded("content_edits", limit)

        visual_data = await _build_visual_data(data)
        visual_data["model_type"] = model_type
        existing_avatar = old_visual.get("avatar", "")
        if existing_avatar:
            visual_data["avatar"] = existing_avatar
        if custom_avatar:
            visual_data["custom_avatar"] = True
            visual_data["identity_reference"] = old_visual.get("identity_reference")
            visual_data["body_profile"] = (
                _normalize_body_profile(data.body_profile, data.gender)
                if data.body_profile
                else old_visual.get("body_profile") or _normalize_body_profile(None, data.gender)
            )
            visual_data["style_tags"] = await default_style_tags_for_model("real", data.visual_style_tags)

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
