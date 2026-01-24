"""Authorization helpers for verifying resource ownership."""

import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException, status, Depends
from sqlalchemy import select
from shared.models import User, Chat
from shared.repository import get_session


async def verify_chat_ownership(chat_id: int, user: User) -> Chat:
    async with get_session() as session:
        result = await session.execute(
            select(Chat).where(Chat.id == chat_id)
        )
        chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "chat_not_found",
                "message": f"Chat {chat_id} not found",
                "code": "CHAT_NOT_FOUND"
            }
        )

    if chat.user_id != user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "access_denied",
                "message": f"You don't have access to chat {chat_id}",
                "code": "CHAT_ACCESS_DENIED"
            }
        )

    return chat


async def verify_user_id_match(requested_user_id: int, user: User):
    if requested_user_id != user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "access_denied",
                "message": f"You can only access your own user data",
                "code": "USER_ACCESS_DENIED"
            }
        )


async def get_owned_chat(
    chat_id: int,
    user: User = Depends(lambda: None) 
) -> Chat:
    return await verify_chat_ownership(chat_id, user)
