import logging

from fastapi import APIRouter, HTTPException, Depends
from pathlib import Path
import sys

from shared.models import User
from shared.services.analytics import AnalyticsService

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database import get_session
from shared.models import Character, Chat, get_async_session
from shared.config import ADMIN_TELEGRAM_IDS
from shared.services.content_loader import get_all_characters, get_character
from shared.services.cache import get_cache
from auth.telegram_auth import get_current_user
router = APIRouter(prefix="/api/characters", tags=["characters"])


@router.get("")
async def list_characters(
    tag: str = None,
    style: str = None,
    creator_type: str = None,  # "all" -> me+public, "me", "public"
    nsfw: str = None,  # "only" — только NSFW, "exclude" — скрыть NSFW
    user: User = Depends(get_current_user)
):
    """List all characters with filtering"""
    characters = await get_all_characters(tag=tag)
    result = []

    for char_id, char in characters.items():
        char_tags = char.get("tags", [])
        model_type = char.get("model_type", "real")

        # у созданных этот параметр 100% будет, поэтому тут ставим такой дефолт
        is_public = char.get("is_public", True)

        if style and style != model_type:
            continue

        if not is_public and char.get("author", {}).get("user_id", 0) != user.telegram_id:
            continue

        if creator_type == "me" and char.get("author", {}).get("user_id", 0) != user.telegram_id:
            continue

        if creator_type == "public" and char.get("author", {}).get("user_id", 0) == user.telegram_id:
            continue

        char_is_nsfw = char.get("is_nsfw", False)
        if nsfw == "only" and not char_is_nsfw:
            continue
        if nsfw == "exclude" and char_is_nsfw:
            continue

        logging.info(f"Добавляем перса: {char['name']}")
        logging.info(f"{creator_type=}")
        result.append({
            "id": char_id,
            "name": char["name"],
            "short_description": char.get("short_description", ""),
            "avatar": char["avatar"],
            "tags": char_tags,
            "model_type": model_type,
            "scenarios_count": 1 + len(char.get("alternate_greetings", [])),
            "author": char.get("author", {"display_name": "AiKai Team"}),
            "is_nsfw": char.get("is_nsfw", False)
        })

    return {"characters": result}


@router.get("/{character_id}")
async def get_character_detail(character_id: str, user: User = Depends(get_current_user)):
    """Detailed character information"""
    char = await get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail={"error": "not_found", "code": "CHARACTER_NOT_FOUND"})

    scenarios = [{
        "index": 0,
        "name": "Основной",
        "preview": char["first_mes"]
    }]

    for i, alt in enumerate(char.get("alternate_greetings", []), 1):
        scenarios.append({
            "index": i,
            "name": f"Сценарий {i}",
            "preview": alt
        })
    async with get_session() as session:
        await AnalyticsService.track(
            session,
            user.id,
            "character_click",
            "characters",
            character_id
        )

    return {
        "id": character_id,
        "name": char["name"],
        "description": char["description"][:500] if len(char["description"]) > 500 else char["description"],
        "personality": char["personality"],
        "avatar": char["avatar"],
        "tags": char.get("tags", []),
        "scenarios": scenarios,
        "appearance": char["appearance"],
        "model_type": char["model_type"],
        "author": char.get("author", {"display_name": "AiKai Team"})
    }


@router.get("/filters/options")
async def get_filter_options():
    """Return available filter options dynamically from loaded JSONs"""
    characters = await get_all_characters()

    all_tags = set()
    styles = set()

    for char in characters.values():
        # Собираем уникальные теги
        if "tags" in char:
            all_tags.update(char["tags"])
        # Собираем стили
        styles.add(char.get("model_type", "real"))  # fixme точно ли надо для model_type ставить дефолтное значение?

    return {
        "tags": sorted(list(all_tags)),
        "styles": sorted(list(styles))
    }


@router.delete("/{character_id}")
async def delete_character(
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Delete a character. Users can only delete their own; admins can delete any."""
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    is_admin = user.telegram_id in ADMIN_TELEGRAM_IDS
    is_owner = character.created_by_username_id == user.telegram_id

    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="You can only delete your own characters")

    if not is_admin and character.created_by_username_id is None:
        raise HTTPException(status_code=403, detail="Cannot delete system characters")

    # Удаляем все чаты с этим персонажем (сообщения/картинки каскадно)
    chats_result = await db.execute(
        select(Chat).where(Chat.chat_type == "character", Chat.target_id == character_id)
    )
    chats = chats_result.scalars().all()

    cache = get_cache()
    for chat in chats:
        await db.delete(chat)
        if cache:
            await cache.invalidate_chat_state(chat.id)

    await db.delete(character)
    await db.commit()

    if cache:
        await cache.invalidate_character(character_id)

    return {"success": True}
