import logging
import uuid

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select

from shared.services.cache import get_cache
from shared.services.subscription import get_subscription_service
from shared.services.image_storage import save_world_cover, get_public_url
from shared.models import User, World
from shared.database import get_session
from auth.telegram_auth import get_current_user

from .cw_schemas import CreateWorldRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/create_world")
async def create_world(
    data: CreateWorldRequest,
    user: User = Depends(get_current_user),
):
    if not data.name or not data.description or not data.intro_message:
        raise HTTPException(status_code=400, detail="Name, description, and intro message are required")

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "worlds_created", session)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("worlds_created", limit)

    world_id = f"custom_{user.telegram_id}_{uuid.uuid4().hex[:8]}"

    async with get_session() as db:
        result = await db.execute(select(World).where(World.id == world_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="World ID collision, please retry")

        tags = [tag.strip() for tag in data.tags if tag.strip()]

        scenarios = [
            {
                "index": 0,
                "intro": data.intro_message,
                "gm_instructions": data.gm_instructions or ""
            }
        ]
        for idx, alt in enumerate(data.alternate_scenarios, start=1):
            if alt.title.strip() or alt.intro.strip():
                scenarios.append({
                    "index": idx,
                    "title": alt.title.strip(),
                    "intro": alt.intro.strip(),
                    "gm_instructions": alt.gm_instructions.strip()
                })

        cover_image = None
        if data.cover_image_url:
            try:
                cover_path = await save_world_cover(data.cover_image_url, world_id)
                cover_image = get_public_url(cover_path)
            except Exception as e:
                logger.warning(f"Failed to save world cover: {e}, using original URL")
                cover_image = data.cover_image_url

        new_world = World(
            id=world_id,
            name=data.name,
            short_description=data.short_description or "",
            description=data.description,
            cover_image=cover_image,
            scenarios=scenarios,
            locations=[],
            tags=tags,
            is_nsfw=False,
            created_by_username_id=user.telegram_id,
            created_by_username=user.username,
        )

        db.add(new_world)
        await db.commit()

        await sub_service.increment_usage(user.telegram_id, "worlds_created", db)

    cache = get_cache()
    if cache:
        await cache.invalidate_world(world_id)

    logger.info(f"User {user.telegram_id} created world '{world_id}'")

    return {"world_id": world_id}


@router.put("/api/worlds/{world_id}")
async def update_world(
    world_id: str,
    data: CreateWorldRequest,
    user: User = Depends(get_current_user),
):
    async with get_session() as db:
        result = await db.execute(select(World).where(World.id == world_id))
        world = result.scalar_one_or_none()

        if not world:
            raise HTTPException(status_code=404, detail="World not found")

        if world.created_by_username_id != user.telegram_id:
            raise HTTPException(status_code=403, detail="You can only edit your own worlds")

        if not data.name or not data.description or not data.intro_message:
            raise HTTPException(status_code=400, detail="Name, description, and intro message are required")

        sub_service = get_subscription_service()
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "content_edits", db)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("content_edits", limit)
        await sub_service.increment_usage(user.telegram_id, "content_edits", db)

        scenarios = [
            {
                "index": 0,
                "intro": data.intro_message,
                "gm_instructions": data.gm_instructions or ""
            }
        ]
        for idx, alt in enumerate(data.alternate_scenarios, start=1):
            if alt.title.strip() or alt.intro.strip():
                scenarios.append({
                    "index": idx,
                    "title": alt.title.strip(),
                    "intro": alt.intro.strip(),
                    "gm_instructions": alt.gm_instructions.strip()
                })

        if data.cover_image_url and data.cover_image_url != world.cover_image:
            try:
                cover_path = await save_world_cover(data.cover_image_url, world_id)
                world.cover_image = get_public_url(cover_path)
            except Exception as e:
                logger.warning(f"Failed to save world cover: {e}, using provided URL")
                world.cover_image = data.cover_image_url

        world.name = data.name
        world.short_description = data.short_description or ""
        world.description = data.description
        world.scenarios = scenarios
        world.tags = [tag.strip() for tag in data.tags if tag.strip()]

        await db.commit()

    cache = get_cache()
    if cache:
        await cache.invalidate_world(world_id)

    logger.info(f"User {user.telegram_id} updated world '{world_id}'")

    return {"success": True}
