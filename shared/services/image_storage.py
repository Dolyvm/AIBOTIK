"""Storage helpers for generated images, avatars, and world cover uploads."""
import logging
import base64
import re
import shutil
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


def _local_images_path(image_url: str) -> Path | None:
    if not image_url.startswith("/images/"):
        return None
    relative_path = image_url.removeprefix("/images/").lstrip("/")
    storage_root = Path(IMAGES_STORAGE_PATH).resolve()
    full_path = (storage_root / relative_path).resolve()
    if storage_root not in full_path.parents and full_path != storage_root:
        raise ImageStorageError("Invalid local image path")
    return full_path


async def local_image_to_data_url(image_url: str) -> str:
    """Read a local /images/... file as a data URL."""
    full_path = _local_images_path(image_url)
    if not full_path:
        raise ImageStorageError("Expected local /images/... URL")
    if not full_path.exists() or not full_path.is_file():
        raise ImageStorageError(f"Local image not found: {image_url}")

    content_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(full_path.suffix.lower(), "image/png")

    async with aiofiles.open(full_path, "rb") as f:
        content = await f.read()
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


async def save_avatar(provider_url: str, character_id: str) -> str:
    """Download or decode an avatar and save it under avatars/."""
    try:
        avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
        avatars_dir.mkdir(parents=True, exist_ok=True)

        decoded = _decode_data_url(provider_url)
        if decoded:
            content, content_type = decoded
        else:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(provider_url) as response:
                    if response.status != 200:
                        raise ImageStorageError(f"Failed to download avatar: HTTP {response.status}")
                    content_type = response.headers.get("Content-Type", "image/png")
                    content_type = content_type.split(";", 1)[0].strip()
                    content = await response.read()

        extension = ALLOWED_CONTENT_TYPES.get(content_type, ".png")
        filename = f"{character_id}_{uuid.uuid4().hex[:8]}{extension}"
        full_path = avatars_dir / filename
        local_path = f"avatars/{filename}"

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)

        logger.info("Avatar saved: %s", local_path)
        return local_path
    except aiohttp.ClientError as e:
        logger.error("Network error downloading avatar: %s", e)
        raise ImageStorageError(f"Network error: {e}") from e
    except IOError as e:
        logger.error("IO error saving avatar: %s", e)
        raise ImageStorageError(f"Storage error: {e}") from e


def copy_as_avatar(source_local_path: str, character_id: str) -> str:
    src = Path(IMAGES_STORAGE_PATH) / source_local_path
    if not src.exists():
        raise ImageStorageError(f"Source file not found: {source_local_path}")

    avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    extension = src.suffix or ".png"
    filename = f"{character_id}_{uuid.uuid4().hex[:8]}{extension}"
    dst = avatars_dir / filename
    shutil.copy2(str(src), str(dst))

    local_path = f"avatars/{filename}"
    logger.info("Avatar copied: %s -> %s", source_local_path, local_path)
    return local_path


async def persist_avatar_reference(avatar_url: str, character_id: str) -> str:
    """Persist an avatar reference and return a public /images/... path."""
    if not avatar_url:
        raise ImageStorageError("Avatar URL is required")

    local_path = _local_images_path(avatar_url)
    if local_path:
        copied_path = copy_as_avatar(avatar_url.removeprefix("/images/"), character_id)
        return f"/images/{copied_path}"

    avatar_path = await save_avatar(avatar_url, character_id)
    return f"/images/{avatar_path}"


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
