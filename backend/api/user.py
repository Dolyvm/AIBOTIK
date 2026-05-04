from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from shared.database import get_session
from shared.database.repositories import ChatRepository, UserRepository, LikeRepository
from shared.services.subscription import get_subscription_service
from shared.subscription_plans import PLAN_LIMITS
from shared.models import User, UserSettings, Character, World
from auth.telegram_auth import get_current_user
from auth.authorization import verify_user_id_match


class UpdateSettingsRequest(BaseModel):
    nsfw_blur: Optional[bool] = None
    nickname: Optional[str] = None
    age_confirmed: Optional[bool] = None

router = APIRouter(prefix="/api/user", tags=["user"])


def _scenario_display_name(sc: dict) -> str:
    """Generate human-readable scenario name (mirrors characters.py logic)."""
    idx = sc.get("index", 0)
    if idx == 0:
        return sc.get("title") or "Основной"
    return sc.get("title") or f"Сценарий {idx}"


@router.get("/{user_id}")
async def get_user_profile(user_id: int, user: User = Depends(get_current_user)):
    """User profile"""
    await verify_user_id_match(user_id, user)

    service = get_subscription_service()
    async with get_session() as session:
        db_user = await session.get(User, user.telegram_id)
        if not db_user:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="User not found")
        summary = await service.get_usage_summary(user.telegram_id, session)

    plan_value = summary.get("plan", "free")
    plan_enum = db_user.subscription_plan
    plan_config = PLAN_LIMITS[plan_enum]

    return {
        "telegram_id": db_user.telegram_id,
        "username": db_user.username,
        "avatar_url": db_user.avatar_url,
        "balance": db_user.balance,
        "nsfw_blur": user.settings.nsfw_blur if user.settings else False,
        "nickname": user.settings.nickname if user.settings else None,
        "age_confirmed": user.settings.age_confirmed if user.settings else False,
        "subscription": {
            "plan": plan_value,
            "plan_display": plan_config.get("display_name", "Free"),
            "end_date": db_user.subscription_end_date.isoformat() if db_user.subscription_end_date else None,
            "auto_renew": db_user.subscription_auto_renew,
        },
        "usage": summary.get("usage", {}),
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


@router.get("/{author_user_id}/author-profile")
async def get_author_profile(
    author_user_id: int,
    user: User = Depends(get_current_user),
):
    """Author profile: their characters, worlds and aggregate stats.

    Special case: author_user_id == 0 returns the AiKai Team profile
    (all system-owned content, i.e. created_by_username_id IS NULL).
    Self-view returns all characters; viewing another user returns only public ones.
    """
    is_team = author_user_id == 0
    is_self = (not is_team) and author_user_id == user.telegram_id

    async with get_session() as session:
        if is_team:
            author = None
            settings = None
            chars_q = select(Character).where(Character.created_by_username_id.is_(None))
            worlds_q = select(World).where(World.created_by_username_id.is_(None))
        else:
            author = await session.get(User, author_user_id)
            if not author:
                raise HTTPException(status_code=404, detail="Author not found")

            settings_row = await session.execute(
                select(UserSettings).where(UserSettings.user_id == author_user_id)
            )
            settings = settings_row.scalar_one_or_none()

            chars_q = select(Character).where(
                Character.created_by_username_id == author_user_id
            )
            if not is_self:
                chars_q = chars_q.where(Character.is_public == True)  # noqa: E712
            worlds_q = select(World).where(World.created_by_username_id == author_user_id)

        chars_res = await session.execute(chars_q)
        worlds_res = await session.execute(worlds_q)
        characters = list(chars_res.scalars().all())
        worlds = list(worlds_res.scalars().all())

        char_ids = [c.id for c in characters]
        world_ids = [w.id for w in worlds]

        like_repo = LikeRepository(session)
        chat_repo = ChatRepository(session)

        message_counts_chars = await chat_repo.get_message_counts_batch("character", char_ids)
        message_counts_worlds = await chat_repo.get_message_counts_batch("world", world_ids)
        chat_session_counts_chars = await chat_repo.get_chat_counts_batch("character", char_ids)
        chat_session_counts_worlds = await chat_repo.get_chat_counts_batch("world", world_ids)
        like_counts = await like_repo.get_like_counts_batch(char_ids)
        user_likes = await like_repo.get_liked_character_ids(user.telegram_id, char_ids)

    nickname = settings.nickname if settings else None
    if is_team:
        display_name = "AiKai Team"
        author_user_id_out = 0
        author_username = None
        author_avatar_url = None
    else:
        if author.username:
            display_name = f"@{author.username}"
        elif nickname:
            display_name = nickname
        else:
            display_name = f"User #{author.telegram_id}"
        author_user_id_out = author.telegram_id
        author_username = author.username
        author_avatar_url = author.avatar_url

    characters_payload = []
    for c in characters:
        visual = c.visual_data or {}
        message_count = message_counts_chars.get(c.id, 0)
        characters_payload.append({
            "id": c.id,
            "name": c.name,
            "short_description": c.short_description or "",
            "avatar": visual.get("avatar", ""),
            "tags": c.tags or [],
            "model_type": visual.get("model_type", "anime"),
            "gender": visual.get("gender", "female"),
            "is_nsfw": c.is_nsfw,
            "is_public": bool(c.is_public),
            "message_count": message_count,
            "chat_count": message_count,
            "chat_session_count": chat_session_counts_chars.get(c.id, 0),
            "like_count": like_counts.get(c.id, 0),
            "is_liked": c.id in user_likes,
        })

    worlds_payload = []
    for w in worlds:
        message_count = message_counts_worlds.get(w.id, 0)
        worlds_payload.append({
            "id": w.id,
            "name": w.name,
            "short_description": w.short_description or "",
            "cover_image": w.cover_image or "",
            "tags": w.tags or [],
            "is_nsfw": w.is_nsfw,
            "message_count": message_count,
            "chat_count": message_count,
            "chat_session_count": chat_session_counts_worlds.get(w.id, 0),
        })

    total_likes = sum(c["like_count"] for c in characters_payload)
    total_messages = sum(c["message_count"] for c in characters_payload) + sum(
        w["message_count"] for w in worlds_payload
    )
    total_chat_sessions = sum(c["chat_session_count"] for c in characters_payload) + sum(
        w["chat_session_count"] for w in worlds_payload
    )

    return {
        "author": {
            "user_id": author_user_id_out,
            "username": author_username,
            "nickname": nickname,
            "avatar_url": author_avatar_url,
            "display_name": display_name,
            "is_team": is_team,
        },
        "stats": {
            "total_likes": total_likes,
            "total_messages": total_messages,
            "total_chats": total_messages,
            "total_chat_sessions": total_chat_sessions,
            "characters_count": len(characters_payload),
            "worlds_count": len(worlds_payload),
        },
        "characters": characters_payload,
        "worlds": worlds_payload,
    }


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
            nickname=payload.nickname,
            age_confirmed=payload.age_confirmed
        )

    return {"success": True}
