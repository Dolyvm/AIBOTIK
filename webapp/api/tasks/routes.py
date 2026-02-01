import json
import logging
from fastapi import APIRouter, HTTPException

from shared.services.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
async def get_task_status(task_id: str):
    redis = await get_redis()

    data = await redis.get(f"task:{task_id}")

    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON for task {task_id}")
            return {"status": "failed", "error": "Invalid task data"}

    return {"status": "not_found"}
