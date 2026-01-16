from fastapi import APIRouter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.services.content_loader import get_all_worlds

router = APIRouter(prefix="/api/worlds", tags=["worlds"])

WORLDS = get_all_worlds()


@router.get("")
async def list_worlds(
    genre: str = None,
    rating: str = None
):
    """List all worlds"""
    result = []

    for world_id, world in WORLDS.items():
        filters = world.get("filters", {})

        if genre and filters.get("genre") != genre:
            continue
        if rating and filters.get("rating") != rating:
            continue

        description_short = world["description"][:150] + "..." if len(world["description"]) > 150 else world["description"]

        result.append({
            "id": world_id,
            "name": world["name"],
            "cover_image": world["cover_image"],
            "tags": world["tags"],
            "description_short": description_short
        })

    return {"worlds": result}


@router.get("/{world_id}")
async def get_world_detail(world_id: str):
    """World details with scenarios"""
    world = WORLDS.get(world_id)
    if not world:
        return {"error": "Not found"}, 404

    scenarios = [{
        "index": 0,
        "name": "Основной",
        "preview": world.get("intro_message", "")
    }]

    for i, alt in enumerate(world.get("alternate_scenarios", []), 1):
        scenarios.append({
            "index": i,
            "name": alt.get("name", f"Сценарий {i}"),
            "preview": alt.get("intro", "")
        })

    return {
        **world,
        "scenarios": scenarios
    }
