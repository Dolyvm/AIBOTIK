from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from shared.database import get_session
from shared.database.repositories import ChatRepository, UserRepository
from shared.services.content_loader import get_character, get_world
from shared.models import User, Character, World
from auth.telegram_auth import get_current_user
from auth.authorization import verify_user_id_match


class UpdateSettingsRequest(BaseModel):
    nsfw_blur: Optional[bool] = None
    nickname: Optional[str] = None

router = APIRouter(prefix="/api/user", tags=["user"])


def _scenario_display_name(sc: dict) -> str:
    """Generate human-readable scenario name (mirrors characters.py logic)."""
    idx = sc.get("index", 0)
    if idx == 0:
        return "Основной"
    return sc.get("title") or f"Сценарий {idx}"


@router.get("/{user_id}")
async def get_user_profile(user_id: int, user: User = Depends(get_current_user)):
    """User profile"""
    await verify_user_id_match(user_id, user)

    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "balance": user.balance,
        "nsfw_blur": user.settings.nsfw_blur if user.settings else True,
        "nickname": user.settings.nickname if user.settings else None
    }


@router.get("/{user_id}/chats")
async def get_user_active_chats(user_id: int, user: User = Depends(get_current_user)):
    """User's active chats with resolved names"""
    await verify_user_id_match(user_id, user)

    async with get_session() as session:
        chat_repo = ChatRepository(session)
        chats = await chat_repo.get_user_chats(user.telegram_id)

        # Collect unique target IDs per type to batch-fetch from DB
        char_ids = {c.target_id for c in chats if c.chat_type == "character"}
        world_ids = {c.target_id for c in chats if c.chat_type == "world"}

        chars_by_id = {}
        worlds_by_id = {}

        if char_ids:
            rows = await session.execute(select(Character).where(Character.id.in_(char_ids)))
            for char in rows.scalars():
                chars_by_id[char.id] = char

        if world_ids:
            rows = await session.execute(select(World).where(World.id.in_(world_ids)))
            for world in rows.scalars():
                worlds_by_id[world.id] = world

    result = []

    for chat in chats:
        chat_data = {
            "id": chat.id,
            "type": chat.chat_type,
            "target_id": chat.target_id,
            "is_active": chat.is_active,
            "updated_at": chat.updated_at.isoformat(),
            "name": chat.target_id,
            "scenario_name": None
        }

        if chat.chat_type == "character":
            char = chars_by_id.get(chat.target_id)
            if char:
                visual = char.visual_data or {}
                chat_data["name"] = char.name
                chat_data["avatar"] = visual.get("avatar", "")
                scenarios = char.scenarios or []
                sc = next((s for s in scenarios if s.get("index") == chat.scenario_index), None)
                chat_data["scenario_name"] = _scenario_display_name(sc) if sc else None
        else:  # world
            world = worlds_by_id.get(chat.target_id)
            if world:
                chat_data["name"] = world.name
                chat_data["avatar"] = world.cover_image or ""
                scenarios = world.scenarios or []
                sc = next((s for s in scenarios if s.get("index") == chat.scenario_index), None)
                chat_data["scenario_name"] = _scenario_display_name(sc) if sc else None

        result.append(chat_data)

    return {"chats": result}


@router.patch("/{user_id}/settings")
async def update_user_settings(
    user_id: int,
    payload: UpdateSettingsRequest,
    user: User = Depends(get_current_user)
):
    await verify_user_id_match(user_id, user)

    async with get_session() as session:
        user_repo = UserRepository(session)
        await user_repo.update_settings(
            telegram_id=user.telegram_id,
            nsfw_blur=payload.nsfw_blur,
            nickname=payload.nickname
        )

    return {"success": True}
