"""Репозиторий для работы с изображениями."""
from sqlalchemy import select, delete

from shared.models import GeneratedImage
from .base import BaseRepository


class GeneratedImageRepository(BaseRepository[GeneratedImage]):
    model = GeneratedImage

    async def get_by_chat(self, chat_id: int) -> list[GeneratedImage]:
        result = await self.session.execute(
            select(GeneratedImage)
            .where(GeneratedImage.chat_id == chat_id)
            .order_by(GeneratedImage.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_chat_formatted(self, chat_id: int) -> list[dict]:
        """Возвращает изображения в формате для API."""
        images = await self.get_by_chat(chat_id)
        return [
            {
                "role": "assistant",
                "avatar": img.public_url,
                "timestamp": img.created_at.isoformat(),
                "nsfw_level": img.nsfw_level or 0
            }
            for img in images
        ]

    async def delete_by_chat(self, chat_id: int) -> int:
        result = await self.session.execute(
            delete(GeneratedImage).where(GeneratedImage.chat_id == chat_id)
        )
        await self.session.commit()
        return result.rowcount
