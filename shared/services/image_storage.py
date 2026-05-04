"""Image storage — download, save, and manage generated images on disk."""
import os
import uuid
import shutil
import logging
import base64
import re
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


DATA_URL_RE = re.compile(r"^data:(?P<content_type>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", re.DOTALL)


async def _save_image_bytes(
    content: bytes,
    content_type: str,
    directory: Path,
    local_dir: str,
    filename_prefix: str = "",
) -> Tuple[str, int, str]:
    directory.mkdir(parents=True, exist_ok=True)
    extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{filename_prefix}{timestamp}_{unique_id}{extension}"
    full_path = directory / filename

    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)

    return f"{local_dir}/{filename}", len(content), content_type


def _decode_data_url(data_url: str) -> tuple[bytes, str] | None:
    match = DATA_URL_RE.match(data_url)
    if not match:
        return None
    content_type = match.group("content_type").split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        content_type = "image/png"
    try:
        data = "".join(match.group("data").split())
        return base64.b64decode(data, validate=True), content_type
    except Exception as e:
        raise ImageStorageError(f"Invalid base64 image data: {e}") from e


async def download_and_save_image(
    provider_url: str,
    user_id: int,
) -> Tuple[str, int, str]:
    """Download image from provider and save to user directory.
    Returns (local_path, file_size, content_type).
    """
    try:
        decoded = _decode_data_url(provider_url)
        if decoded:
            content, content_type = decoded
            return await _save_image_bytes(
                content,
                content_type,
                Path(IMAGES_STORAGE_PATH) / str(user_id),
                str(user_id),
            )

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

        decoded = _decode_data_url(provider_url)
        if decoded:
            content, content_type = decoded
            extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")
        else:
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

        unique_suffix = uuid.uuid4().hex[:8]
        filename = f"{character_id}_{unique_suffix}{extension}"
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
    unique_suffix = uuid.uuid4().hex[:8]
    filename = f"{character_id}_{unique_suffix}{extension}"
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
