from fastapi import APIRouter, HTTPException
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.services.content_loader import get_all_worlds, get_world

router = APIRouter(prefix="/api/worlds", tags=["worlds"])


@router.get("")
async def list_worlds(
    tag: str = None,
    rating: str = None
):
    """List all worlds"""
    worlds = await get_all_worlds(tag=tag)
    result = []

    for world_id, world in worlds.items():
        world_tags = world.get("tags", [])
        filters = world.get("filters", {})
        # Фильтрация по рейтингу (если нужно)
        if rating and filters.get("rating") != rating:
            continue

        description_short = world["description"][:150] + "..." if len(world["description"]) > 150 else world["description"]

        result.append({
            "id": world_id,
            "name": world["name"],
            "cover_image": world.get("cover_image", ""),
            "tags": world_tags,
            "description_short": description_short,
            "is_nsfw": world.get("is_nsfw", False)
        })

    return {"worlds": result}


@router.get("/{world_id}")
async def get_world_detail(world_id: str):
    """World details with scenarios"""
    world = await get_world(world_id)
    if not world:
        raise HTTPException(status_code=404, detail={"error": "not_found", "code": "WORLD_NOT_FOUND"})

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


@router.get("/filters/options")
async def get_world_filter_options():
    """Return available filter options"""
    worlds = await get_all_worlds()

    all_tags = set()
    for world in worlds.values():
        if "tags" in world:
            all_tags.update(world["tags"])
    return {
        "tags": sorted(list(all_tags))
    }
