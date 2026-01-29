"""Репозиторий для работы с сообщениями."""
from sqlalchemy import select, update, delete

from shared.models import Message, MessageRole, Chat
from .base import BaseRepository
from ..validators import validate_enum_value


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def add(
        self,
        chat_id: int,
        role: str,
        content: str,
        tokens_used: int = 0,
        is_auto_generated: bool = False
    ) -> Message:
        role_enum = validate_enum_value(role, MessageRole, "role")

        message = Message(
            chat_id=chat_id,
            role=role_enum,
            content=content,
            tokens_used=tokens_used,
            is_auto_generated=is_auto_generated
        )
        self.session.add(message)

        await self.session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(msgs_since_summary=Chat.msgs_since_summary + 1)
        )

        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def get_history(self, chat_id: int, limit: int = 20) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def delete_by_chat(self, chat_id: int) -> int:
        result = await self.session.execute(
            delete(Message).where(Message.chat_id == chat_id)
        )
        await self.session.commit()
        return result.rowcount
