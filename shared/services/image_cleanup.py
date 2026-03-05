import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import IMAGES_STORAGE_PATH
from shared.models import GeneratedImage, Character, World

logger = logging.getLogger(__name__)


async def collect_chat_image_paths(session: AsyncSession, chat_id: int) -> list[str]:
    """Collect all local_path values for images in a chat."""
    result = await session.execute(
        select(GeneratedImage.local_path)
        .where(GeneratedImage.chat_id == chat_id)
        .where(GeneratedImage.local_path.isnot(None))
    )
    return [row[0] for row in result.all()]


async def collect_images_since(
    session: AsyncSession, chat_id: int, since_dt: datetime
) -> list[str]:
    """Collect local_path values for images created at or after since_dt."""
    result = await session.execute(
        select(GeneratedImage.local_path)
        .where(GeneratedImage.chat_id == chat_id)
        .where(GeneratedImage.created_at >= since_dt)
        .where(GeneratedImage.local_path.isnot(None))
    )
    return [row[0] for row in result.all()]


async def collect_character_file_paths(
    session: AsyncSession,
    character_id: str,
    chat_ids: list[int],
) -> list[str]:
    """Collect all file paths for a character: chat images + avatar."""
    paths: list[str] = []

    # Chat images
    if chat_ids:
        result = await session.execute(
            select(GeneratedImage.local_path)
            .where(GeneratedImage.chat_id.in_(chat_ids))
            .where(GeneratedImage.local_path.isnot(None))
        )
        paths.extend(row[0] for row in result.all())

    # Avatar file
    result = await session.execute(
        select(Character.visual_data).where(Character.id == character_id)
    )
    row = result.scalar_one_or_none()
    if row and isinstance(row, dict):
        avatar = row.get("avatar", "")
        if avatar and avatar.startswith("/images/avatars/"):
            paths.append(avatar.removeprefix("/images/"))

    return paths


async def collect_world_file_paths(
    session: AsyncSession,
    world_id: str,
    chat_ids: list[int],
) -> list[str]:
    """Collect all file paths for a world: chat images + cover."""
    paths: list[str] = []

    # Chat images
    if chat_ids:
        result = await session.execute(
            select(GeneratedImage.local_path)
            .where(GeneratedImage.chat_id.in_(chat_ids))
            .where(GeneratedImage.local_path.isnot(None))
        )
        paths.extend(row[0] for row in result.all())

    # Cover image file
    result = await session.execute(
        select(World.cover_image).where(World.id == world_id)
    )
    cover = result.scalar_one_or_none()
    if cover and isinstance(cover, str) and "/images/world_covers/" in cover:
        # Extract relative path from public URL
        idx = cover.find("world_covers/")
        if idx != -1:
            paths.append(cover[idx:])

    return paths


def delete_files(paths: list[str]) -> int:
    """Delete files from disk. Returns count of successfully deleted files."""
    deleted = 0
    for rel_path in paths:
        try:
            full_path = Path(IMAGES_STORAGE_PATH) / rel_path
            if full_path.exists():
                full_path.unlink()
                logger.info(f"Deleted file: {rel_path}")
                deleted += 1
        except OSError as e:
            logger.warning(f"Failed to delete {rel_path}: {e}")
    return deleted
