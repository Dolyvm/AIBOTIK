from fastapi import APIRouter
import json
from pathlib import Path

router = APIRouter(prefix="/api/worlds", tags=["worlds"])


def load_worlds():
    """Load all worlds from JSON files"""
    worlds = {}
    worlds_dir = Path("/app/content/worlds")
    for json_file in worlds_dir.glob("*.json"):
        with open(json_file) as f:
            world = json.load(f)
            worlds[world["id"]] = world
    return worlds


WORLDS = load_worlds()


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

    # Build scenarios list with full text (no truncation)
    scenarios = [{
        "index": 0,
        "name": "Основной",
        "preview": world.get("intro_message", "")
    }]

    # Add alternate scenarios if they exist
    for i, alt in enumerate(world.get("alternate_scenarios", []), 1):
        scenarios.append({
            "index": i,
            "name": alt.get("name", f"Сценарий {i}"),
            "preview": alt.get("intro", "")
        })

    # Return world data with scenarios
    return {
        **world,
        "scenarios": scenarios
    }
