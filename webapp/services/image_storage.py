import os
import uuid
import aiohttp
import aiofiles
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

IMAGES_STORAGE_PATH = os.getenv("IMAGES_STORAGE_PATH", "/app/generated_images")
IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost/images")

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class ImageStorageError(Exception):
    """Ошибка при сохранении изображения"""
    pass


async def download_and_save_image(
    provider_url: str,
    user_id: int,
    convert_to_webp: bool = False
) -> Tuple[str, int, str]:
    try:
        user_dir = Path(IMAGES_STORAGE_PATH) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]

        async with aiohttp.ClientSession() as session:
            async with session.get(provider_url, timeout=30) as response:
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
    """Преобразует локальный путь в публичный URL"""
    return f"{IMAGES_BASE_URL}/{local_path}"


def delete_image(local_path: str) -> bool:
    """Удаляет изображение с диска"""
    try:
        full_path = Path(IMAGES_STORAGE_PATH) / local_path
        if full_path.exists():
            full_path.unlink()
            logger.info(f"Image deleted: {local_path}")
            return True
        return False
    except IOError as e:
        logger.error(f"Error deleting image {local_path}: {e}")
        return False


async def save_avatar(provider_url: str, character_id: str) -> str:
    try:
        avatars_dir = Path(IMAGES_STORAGE_PATH) / "avatars"
        avatars_dir.mkdir(parents=True, exist_ok=True)

        async with aiohttp.ClientSession() as session:
            async with session.get(provider_url, timeout=30) as response:
                if response.status != 200:
                    raise ImageStorageError(
                        f"Failed to download avatar: HTTP {response.status}"
                    )

                content = await response.read()

        filename = f"{character_id}.png"
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
