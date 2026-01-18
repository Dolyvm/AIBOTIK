from fastapi import APIRouter
from pathlib import Path
import sys

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.services.content_loader import get_all_characters

router = APIRouter(prefix="/api/characters", tags=["characters"])

# Load once at startup
CHARACTERS = get_all_characters()

# Character metadata dictionary (no longer loaded from file)
CHARACTER_META = {}


@router.get("")
async def list_characters(
    tag: str = None,   # Переименовали genre -> tag
    style: str = None 
):
    """List all characters with filtering"""
    result = []

    for char_id, char in CHARACTERS.items():
        # Читаем данные напрямую из загруженного JSON
        char_tags = char.get("tags", [])
        model_type = char.get("model_type", "real")

        # Логика фильтрации
        if tag and tag not in char_tags:
            continue
        if style and style != model_type:
            continue

        result.append({
            "id": char_id,
            "name": char["name"],
            "avatar": char["avatar"],
            "tags": char_tags,
            "model_type": model_type,
            "scenarios_count": 1 + len(char.get("alternate_greetings", []))
        })

    return {"characters": result}



@router.get("/{character_id}")
async def get_character_detail(character_id: str):
    """Detailed character information"""
    char = CHARACTERS.get(character_id)
    if not char:
        return {"error": "Not found"}, 404

    meta = CHARACTER_META.get(character_id, {})

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
        "tags": meta.get("tags", []),  # nsfw_tags -> tags, не увидел nsfw_tags в файле.
        "scenarios": scenarios,
        "appearance": char["appearance"],
        "model_type": char["model_type"]
    }


@router.get("/filters/options")
async def get_filter_options():
    """Return available filter options dynamically from loaded JSONs"""
    all_tags = set()
    styles = set()

    for char in CHARACTERS.values():
        # Собираем уникальные теги
        if "tags" in char:
            all_tags.update(char["tags"])
        
        # Собираем стили
        styles.add(char.get("model_type", "real"))

    return {
        "tags": sorted(list(all_tags)), # Переименовали genres -> tags
        "styles": sorted(list(styles))
    }