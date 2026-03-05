import asyncio
import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from shared.database import get_session
from shared.models import GeneratedImage
from shared.config import IMAGES_STORAGE_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GRACE_PERIOD_SECONDS = 24 * 3600  


async def get_all_known_paths() -> set[str]:
    async with get_session() as session:
        result = await session.execute(
            select(GeneratedImage.local_path)
            .where(GeneratedImage.local_path.isnot(None))
        )
        return {row[0] for row in result.all()}


def scan_user_dirs(storage_path: str) -> list[tuple[str, Path]]:
    files = []
    storage = Path(storage_path)
    if not storage.exists():
        return files

    now = time.time()

    for entry in storage.iterdir():
        if not entry.is_dir() or not entry.name.isdigit():
            continue

        for file_path in entry.iterdir():
            if not file_path.is_file():
                continue

            mtime = file_path.stat().st_mtime
            if (now - mtime) < GRACE_PERIOD_SECONDS:
                continue

            relative_path = f"{entry.name}/{file_path.name}"
            files.append((relative_path, file_path))

    return files


async def main():
    parser = argparse.ArgumentParser(description="Cleanup orphan images from disk")
    parser.add_argument("--delete", action="store_true", help="Actually delete orphan files (default: dry-run)")
    args = parser.parse_args()

    logger.info(f"Scanning {IMAGES_STORAGE_PATH} for orphan images...")

    known_paths = await get_all_known_paths()
    logger.info(f"Found {len(known_paths)} images tracked in database")

    disk_files = scan_user_dirs(IMAGES_STORAGE_PATH)
    logger.info(f"Found {len(disk_files)} files on disk (outside grace period)")

    orphans = [(rel, full) for rel, full in disk_files if rel not in known_paths]
    logger.info(f"Found {len(orphans)} orphan files")

    if not orphans:
        logger.info("No orphans to clean up.")
        return

    deleted = 0
    for rel_path, full_path in orphans:
        if args.delete:
            try:
                full_path.unlink()
                logger.info(f"Deleted: {rel_path}")
                deleted += 1
            except OSError as e:
                logger.warning(f"Failed to delete {rel_path}: {e}")
        else:
            logger.info(f"[DRY-RUN] Would delete: {rel_path} ({full_path.stat().st_size} bytes)")

    if args.delete:
        logger.info(f"Cleanup complete: {deleted}/{len(orphans)} files deleted")
    else:
        logger.info(f"Dry-run complete: {len(orphans)} orphans found. Run with --delete to remove them.")


if __name__ == "__main__":
    asyncio.run(main())
