from fastapi import APIRouter, Depends
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.repository import get_user, get_user_chats
from shared.services.content_loader import get_character, get_world
from shared.models import User
from auth.telegram_auth import get_current_user
from auth.authorization import verify_user_id_match

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/{user_id}")
async def get_user_profile(user_id: int, user: User = Depends(get_current_user)):
    """User profile"""
    await verify_user_id_match(user_id, user)

    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "balance": user.balance,
        "nsfw_blur": user.settings.nsfw_blur if user.settings else True
    }


@router.get("/{user_id}/chats")
async def get_user_active_chats(user_id: int, user: User = Depends(get_current_user)):
    """User's active chats with resolved names"""
    await verify_user_id_match(user_id, user)

    chats = await get_user_chats(user.telegram_id)

    result = []

    for chat in chats:
        chat_data = {
            "id": chat.id,
            "type": chat.chat_type,
            "target_id": chat.target_id,
            "is_active": chat.is_active,
            "updated_at": chat.updated_at.isoformat(),
            "name": chat.target_id
        }

        if chat.chat_type == "character":
            character = await get_character(chat.target_id)
            if character:
                chat_data["name"] = character["name"]
                chat_data["avatar"] = character.get("avatar", "")
        else:  # world
            world = await get_world(chat.target_id)
            if world:
                chat_data["name"] = world["name"]
                chat_data["avatar"] = world.get("cover_image", "")

        result.append(chat_data)

    return {"chats": result}
