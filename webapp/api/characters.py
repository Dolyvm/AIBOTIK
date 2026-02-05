from fastapi import APIRouter, HTTPException, Depends
from pathlib import Path
import sys

from shared.models import User

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.services.content_loader import get_all_characters, get_character
from auth.telegram_auth import get_current_user
router = APIRouter(prefix="/api/characters", tags=["characters"])


@router.get("")
async def list_characters(
    tag: str = None,
    style: str = None,
    user: User = Depends(get_current_user)
):
    """List all characters with filtering"""
    characters = await get_all_characters(tag=tag)
    result = []

    for char_id, char in characters.items():
        char_tags = char.get("tags", [])
        model_type = char.get("model_type", "real")
        is_public = char.get("is_public", False)

        if style and style != model_type:
            continue

        if not is_public and char.get("author", {"display_name": "AiKai Team"}) != user.telegram_id:
            continue

        result.append({
            "id": char_id,
            "name": char["name"],
            "avatar": char["avatar"],
            "tags": char_tags,
            "model_type": model_type,
            "scenarios_count": 1 + len(char.get("alternate_greetings", [])),
            "author": char.get("author", {"display_name": "AiKai Team"}),
            "is_nsfw": char.get("is_nsfw", False)
        })

    return {"characters": result}


@router.get("/{character_id}")
async def get_character_detail(character_id: str):
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
