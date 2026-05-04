import json
import logging
from fastapi import APIRouter, Header, HTTPException, status

from auth.authorization import verify_chat_ownership
from auth.telegram_auth import get_current_user
from shared.services.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
async def get_task_status(task_id: str, authorization: str | None = Header(None)):
    redis = await get_redis()

    data = await redis.get(f"task:{task_id}")

    if data:
        try:
            task_data = json.loads(data)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON for task {task_id}")
            return {"status": "failed", "error": "Invalid task data"}

        await _verify_task_access(task_data, authorization)
        return task_data

    return {"status": "not_found"}


async def _verify_task_access(task_data: dict, authorization: str | None) -> None:
    """Protect chat/user-owned tasks while preserving legacy anonymous admin tasks."""
    result = task_data.get("result") if isinstance(task_data.get("result"), dict) else {}
    chat_id = task_data.get("chat_id") or result.get("chat_id")
    owner_id = task_data.get("user_id")

    if chat_id is None and owner_id is None:
        return

    user = await get_current_user(authorization=authorization)

    if chat_id is not None:
        try:
            await verify_chat_ownership(int(chat_id), user)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid task chat owner"
            )
        return

    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid task owner"
        )

    if owner_id != user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Task access denied"
        )
