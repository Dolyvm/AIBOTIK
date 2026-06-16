"""Storage helpers for legacy image URLs and world cover uploads."""
import logging
import base64
import re
import uuid
from pathlib import Path

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


def get_public_url(local_path: str) -> str:
    return f"{IMAGES_BASE_URL}/{local_path}"


async def save_avatar_image(image_bytes: bytes, content_type: str, character_id: str) -> str:
    """Save generated avatar bytes and return the public /images URL."""
    try:
        extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")
        safe_character_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", character_id).strip("._")
        if not safe_character_id:
            safe_character_id = "character"

        avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
        avatars_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{safe_character_id}_{uuid.uuid4().hex[:12]}{extension}"
        full_path = avatars_dir / filename

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(image_bytes)

        local_path = f"avatars/{filename}"
        logger.info("Avatar image saved: %s", local_path)
        return f"/images/{local_path}"

    except IOError as e:
        logger.error("IO error saving avatar image: %s", e)
        raise ImageStorageError(f"Storage error: {e}") from e


async def save_world_cover(provider_url: str, world_id: str) -> str:
    """Save a world cover from a remote URL or data URL."""
    try:
        covers_dir = Path(IMAGES_STORAGE_PATH) / "world_covers"
        covers_dir.mkdir(parents=True, exist_ok=True)

        decoded = _decode_data_url(provider_url)
        if decoded:
            content, content_type = decoded
        else:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(provider_url) as response:
                    if response.status != 200:
                        raise ImageStorageError(
                            f"Failed to download cover: HTTP {response.status}"
                        )

                    content_type = response.headers.get("Content-Type", "image/png")
                    content_type = content_type.split(";")[0].strip()
                    content = await response.read()

        extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")
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
