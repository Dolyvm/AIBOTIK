"""Репозиторий для работы с чатами."""
from typing import Optional
from sqlalchemy import select, update, delete

from shared.models import Chat, Message, GeneratedImage
from .base import BaseRepository
from ..validators import validate_chat_type


class ChatRepository(BaseRepository[Chat]):
    model = Chat

    async def create_chat(
        self,
        user_id: int,
        target_id: str,
        chat_type: str,
        scenario_index: int = 0
    ) -> tuple[Chat, bool]:
        """Returns (chat, is_new). If chat for this scenario already exists — returns it as-is."""
        chat_type = validate_chat_type(chat_type)

        result = await self.session.execute(
            select(Chat).where(
                Chat.user_id == user_id,
                Chat.target_id == target_id,
                Chat.chat_type == chat_type,
                Chat.scenario_index == scenario_index
            )
        )
        existing_chat = result.scalar_one_or_none()

        if existing_chat:
            await self.session.execute(
                update(Chat)
                .where(Chat.user_id == user_id, Chat.id != existing_chat.id)
                .values(is_active=False)
            )
            existing_chat.is_active = True
            await self.session.commit()
            await self.session.refresh(existing_chat)
            return existing_chat, False

        await self.session.execute(
            update(Chat)
            .where(Chat.user_id == user_id)
            .values(is_active=False)
        )

        chat = Chat(
            user_id=user_id,
            target_id=target_id,
            chat_type=chat_type,
            scenario_index=scenario_index,
            affinity=0,
            arousal=0,
            current_location=None,
            current_mood="neutral",
            summary="",
            state_meta={},
            is_active=True
        )
        self.session.add(chat)
        await self.session.commit()
        await self.session.refresh(chat)
        return chat, True

    async def get_active(self, user_id: int) -> Optional[Chat]:
        result = await self.session.execute(
            select(Chat)
            .where(Chat.user_id == user_id, Chat.is_active == True)
            .order_by(Chat.updated_at.desc())
        )
        return result.scalar_one_or_none()

    async def get_chats_for_target(self, user_id: int, target_id: str, chat_type: str) -> list[Chat]:
        chat_type = validate_chat_type(chat_type)
        result = await self.session.execute(
            select(Chat).where(
                Chat.user_id == user_id,
                Chat.target_id == target_id,
                Chat.chat_type == chat_type
            )
        )
        return list(result.scalars().all())

    async def get_user_chats(self, user_id: int) -> list[Chat]:
        result = await self.session.execute(
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(Chat.updated_at.desc())
        )
        return list(result.scalars().all())

    async def set_active(self, user_id: int, chat_id: int) -> None:
        await self.session.execute(
            update(Chat)
            .where(Chat.user_id == user_id)
            .values(is_active=False)
        )
        await self.session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(is_active=True)
        )
        await self.session.commit()

    async def update_metrics(self, chat_id: int, metrics: dict) -> None:
        from ..validators import validate_metrics_dict
        metrics = validate_metrics_dict(metrics)

        await self.session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(**metrics)
        )
        await self.session.commit()

    async def reset_history(self, chat_id: int) -> None:
        await self.session.execute(
            delete(Message).where(Message.chat_id == chat_id)
        )
        await self.session.execute(
            delete(GeneratedImage).where(GeneratedImage.chat_id == chat_id)
        )
        await self.session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(
                affinity=0,
                arousal=0,
                current_location=None,
                current_mood="neutral",
                summary="",
                msgs_since_summary=0,
                state_meta={}
            )
        )
        await self.session.commit()
