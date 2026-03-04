import logging
from pathlib import Path
import sys

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import User, World, Chat, get_async_session
from shared.config import ADMIN_TELEGRAM_IDS
from shared.services.content_loader import get_all_worlds, get_world
from shared.services.cache import get_cache
from shared.services.image_cleanup import collect_world_file_paths, delete_files
from auth.telegram_auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worlds", tags=["worlds"])


@router.get("")
async def list_worlds(
    tag: str = None,
    rating: str = None,
    creator_type: str = None,
    user: User = Depends(get_current_user)
):
    """List all worlds"""
    worlds = await get_all_worlds(tag=tag)
    result = []

    for world_id, world in worlds.items():
        world_tags = world.get("tags", [])
        filters = world.get("filters", {})

        if rating and filters.get("rating") != rating:
            continue

        author = world.get("author", {})
        author_user_id = author.get("user_id", 0)

        if creator_type == "me" and author_user_id != user.telegram_id:
            continue

        if creator_type == "public" and author_user_id == user.telegram_id:
            continue

        description_short = world["description"][:150] + "..." if len(world["description"]) > 150 else world["description"]

        result.append({
            "id": world_id,
            "name": world["name"],
            "short_description": world.get("short_description", ""),
            "cover_image": world.get("cover_image", ""),
            "tags": world_tags,
            "description_short": description_short,
            "is_nsfw": world.get("is_nsfw", False),
            "author": author
        })

    return {"worlds": result}


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


@router.get("/{world_id}/edit")
async def get_world_for_edit(
    world_id: str,
    user: User = Depends(get_current_user),
):
    """Full world data for editing — only available to the author"""
    world = await get_world(world_id)
    if not world:
        raise HTTPException(status_code=404, detail={"error": "not_found", "code": "WORLD_NOT_FOUND"})

    author = world.get("author", {})
    if author.get("user_id") != user.telegram_id:
        raise HTTPException(status_code=403, detail="You can only edit your own worlds")

    return {
        "id": world_id,
        "name": world["name"],
        "short_description": world.get("short_description", ""),
        "description": world["description"],
        "gm_instructions": world.get("gm_instructions", ""),
        "intro_message": world.get("intro_message", ""),
        "alternate_scenarios": world.get("alternate_scenarios", []),
        "cover_image": world.get("cover_image", ""),
        "tags": world.get("tags", []),
    }


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
            "name": alt.get("title", f"Сценарий {i}"),
            "preview": alt.get("intro", "")
        })

    return {
        **world,
        "scenarios": scenarios
    }


@router.delete("/{world_id}")
async def delete_world(
    world_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Delete a world. Users can only delete their own; admins can delete any."""
    result = await db.execute(select(World).where(World.id == world_id))
    world = result.scalar_one_or_none()

    if not world:
        raise HTTPException(status_code=404, detail="World not found")

    is_admin = user.telegram_id in ADMIN_TELEGRAM_IDS
    is_owner = world.created_by_username_id == user.telegram_id

    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="You can only delete your own worlds")

    if not is_admin and world.created_by_username_id is None:
        raise HTTPException(status_code=403, detail="Cannot delete system worlds")

    # Delete all associated chats (messages/images cascade)
    chats_result = await db.execute(
        select(Chat).where(Chat.chat_type == "world", Chat.target_id == world_id)
    )
    chats = chats_result.scalars().all()
    chat_ids = [c.id for c in chats]

    paths = await collect_world_file_paths(db, world_id, chat_ids)

    cache = get_cache()
    for chat in chats:
        await db.delete(chat)
        if cache:
            await cache.invalidate_chat_state(chat.id)

    await db.delete(world)
    await db.commit()

    delete_files(paths)

    if cache:
        await cache.invalidate_world(world_id)

    return {"success": True}
