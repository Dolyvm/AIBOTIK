from fastapi import APIRouter, HTTPException, Depends
from pathlib import Path
import sys

from auth.telegram_auth import get_current_user
from shared.database import get_session
from shared.models import User
from shared.services.analytics import AnalyticsService

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.services.content_loader import get_all_worlds, get_world

router = APIRouter(prefix="/api/worlds", tags=["worlds"])


@router.get("")
async def list_worlds(
    tag: str = None,
    rating: str = None,
    creator_type: str = None  # "all" -> me+public, "me", "public"
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

        # todo фильтр по creator_type.

        description_short = world["description"][:150] + "..." if len(world["description"]) > 150 else world["description"]

        result.append({
            "id": world_id,
            "name": world["name"],
            "short_description": world.get("short_description", ""),
            "cover_image": world.get("cover_image", ""),
            "tags": world_tags,
            "description_short": description_short,
            "is_nsfw": world.get("is_nsfw", False)
        })

    return {"worlds": result}


@router.get("/{world_id}")
async def get_world_detail(world_id: str, user: User = Depends(get_current_user)):
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

    async with get_session() as session:
        await AnalyticsService.track(
            session,
            user.id,
            "world_click",
            "worlds",
            world_id,
            # отслеживать ли тут мету - обсуждаемый вопрос. В создании чата точно надо трекать.
            # meta={
            #     "": ""
            # }
        )

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
