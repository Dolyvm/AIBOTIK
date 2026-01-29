"""Репозиторий для работы с изображениями."""
from typing import Optional
from sqlalchemy import select, delete

from shared.models import GeneratedImage
from .base import BaseRepository


class GeneratedImageRepository(BaseRepository[GeneratedImage]):
    model = GeneratedImage

    async def save(
        self,
        user_id: int,
        chat_id: int,
        prompt: str,
        provider_url: str,
        local_path: Optional[str] = None,
        file_size: Optional[int] = None,
        content_type: Optional[str] = None
    ) -> GeneratedImage:
        image = GeneratedImage(
            user_id=user_id,
            chat_id=chat_id,
            prompt=prompt,
            provider_url=provider_url,
            local_path=local_path,
            file_size=file_size,
            content_type=content_type
        )
        self.session.add(image)
        await self.session.commit()
        await self.session.refresh(image)
        return image

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
                "timestamp": img.created_at.isoformat()
            }
            for img in images
        ]

    async def delete_by_chat(self, chat_id: int) -> int:
        result = await self.session.execute(
            delete(GeneratedImage).where(GeneratedImage.chat_id == chat_id)
        )
        await self.session.commit()
        return result.rowcount
