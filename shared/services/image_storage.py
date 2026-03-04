"""Image storage — download, save, and manage generated images on disk."""
import os
import uuid
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple

import aiohttp
import aiofiles

from shared.config import IMAGES_STORAGE_PATH, IMAGES_BASE_URL

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class ImageStorageError(Exception):
    pass


async def download_and_save_image(
    provider_url: str,
    user_id: int,
) -> Tuple[str, int, str]:
    """Download image from provider and save to user directory.
    Returns (local_path, file_size, content_type).
    """
    try:
        user_dir = Path(IMAGES_STORAGE_PATH) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(provider_url) as response:
                if response.status != 200:
                    raise ImageStorageError(
                        f"Failed to download image: HTTP {response.status}"
                    )

                content_type = response.headers.get("Content-Type", "image/png")
                content_type = content_type.split(";")[0].strip()
                extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")

                filename = f"{timestamp}_{unique_id}{extension}"
                local_path = f"{user_id}/{filename}"
                full_path = user_dir / filename

                content = await response.read()
                file_size = len(content)

                async with aiofiles.open(full_path, "wb") as f:
                    await f.write(content)

        logger.info(f"Image saved: {local_path} ({file_size} bytes)")
        return local_path, file_size, content_type

    except aiohttp.ClientError as e:
        logger.error(f"Network error downloading image: {e}")
        raise ImageStorageError(f"Network error: {e}")
    except IOError as e:
        logger.error(f"IO error saving image: {e}")
        raise ImageStorageError(f"Storage error: {e}")


def get_public_url(local_path: str) -> str:
    return f"{IMAGES_BASE_URL}/{local_path}"


async def save_avatar(provider_url: str, character_id: str) -> str:
    """Download avatar from provider URL and save to avatars/ directory."""
    try:
        avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
        avatars_dir.mkdir(parents=True, exist_ok=True)

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(provider_url) as response:
                if response.status != 200:
                    raise ImageStorageError(
                        f"Failed to download avatar: HTTP {response.status}"
                    )

                content_type = response.headers.get("Content-Type", "image/png")
                content_type = content_type.split(";")[0].strip()
                extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")

                content = await response.read()

        filename = f"{character_id}{extension}"
        full_path = avatars_dir / filename
        local_path = f"avatars/{filename}"

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)

        logger.info(f"Avatar saved: {local_path}")
        return local_path

    except aiohttp.ClientError as e:
        logger.error(f"Network error downloading avatar: {e}")
        raise ImageStorageError(f"Network error: {e}")
    except IOError as e:
        logger.error(f"IO error saving avatar: {e}")
        raise ImageStorageError(f"Storage error: {e}")


def copy_as_avatar(source_local_path: str, character_id: str) -> str:
    """Copy an already-downloaded image as the character's avatar.
    source_local_path is relative to IMAGES_STORAGE_PATH (e.g. '123/20240101_abc12345.webp').
    Returns avatars/<character_id>.<ext>.
    """
    src = Path(IMAGES_STORAGE_PATH) / source_local_path
    if not src.exists():
        raise ImageStorageError(f"Source file not found: {source_local_path}")

    avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    extension = src.suffix or ".png"
    filename = f"{character_id}{extension}"
    dst = avatars_dir / filename

    shutil.copy2(str(src), str(dst))
    local_path = f"avatars/{filename}"
    logger.info(f"Avatar copied: {source_local_path} -> {local_path}")
    return local_path


async def save_world_cover(provider_url: str, world_id: str) -> str:
    """Download and save a world cover image."""
    try:
        covers_dir = Path(IMAGES_STORAGE_PATH) / "world_covers"
        covers_dir.mkdir(parents=True, exist_ok=True)

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(provider_url) as response:
                if response.status != 200:
                    raise ImageStorageError(
                        f"Failed to download cover: HTTP {response.status}"
                    )

                content_type = response.headers.get("Content-Type", "image/png")
                content_type = content_type.split(";")[0].strip()
                extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")

                content = await response.read()

        filename = f"{world_id}{extension}"
        full_path = covers_dir / filename
        local_path = f"world_covers/{filename}"

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)

        logger.info(f"World cover saved: {local_path}")
        return local_path

    except aiohttp.ClientError as e:
        logger.error(f"Network error downloading world cover: {e}")
        raise ImageStorageError(f"Network error: {e}")
    except IOError as e:
        logger.error(f"IO error saving world cover: {e}")
        raise ImageStorageError(f"Storage error: {e}")
