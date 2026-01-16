from fastapi import APIRouter
import sys
import json
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import get_user, get_user_chats
from shared.card_parser import get_character

router = APIRouter(prefix="/api/user", tags=["user"])

# Load worlds for name resolution
def load_worlds():
    worlds = {}
    worlds_dir = Path("/app/content/worlds")
    for json_file in worlds_dir.glob("*.json"):
        with open(json_file) as f:
            world = json.load(f)
            worlds[world["id"]] = world
    return worlds

WORLDS = load_worlds()


@router.get("/{user_id}")
async def get_user_profile(user_id: int):
    """User profile"""
    user = await get_user(user_id)
    if not user:
        return {"error": "Not found"}, 404

    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "balance": user.balance,
        "nsfw_blur": user.nsfw_blur
    }


@router.get("/{user_id}/chats")
async def get_user_active_chats(user_id: int):
    """User's active chats with resolved names"""
    chats = await get_user_chats(user_id)

    result = []
    characters_dir = Path("/app/content/characters")

    for chat in chats:
        chat_data = {
            "id": chat.id,
            "type": chat.chat_type,
            "target_id": chat.target_id,
            "is_active": chat.is_active,
            "updated_at": chat.updated_at.isoformat(),
            "name": chat.target_id  # Default to target_id
        }

        # Resolve name
        if chat.chat_type == "character":
            character = get_character(characters_dir, chat.target_id)
            if character:
                chat_data["name"] = character["name"]
                chat_data["image_url"] = character["image_url"]
        else:  # world
            world = WORLDS.get(chat.target_id)
            if world:
                chat_data["name"] = world["name"]
                chat_data["image_url"] = world.get("cover_image", "")

        result.append(chat_data)

    return {"chats": result}
