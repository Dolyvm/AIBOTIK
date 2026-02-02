"""Репозиторий для работы с промптами."""
from typing import Optional
from sqlalchemy import select, update

from shared.models import Prompt
from .base import BaseRepository


class PromptRepository(BaseRepository[Prompt]):
    model = Prompt

    async def get_by_key(self, key: str) -> Optional[Prompt]:
        result = await self.session.execute(
            select(Prompt).where(Prompt.key == key)
        )
        return result.scalar_one_or_none()

    async def get_all_ordered(self) -> list[Prompt]:
        result = await self.session.execute(
            select(Prompt).order_by(Prompt.category, Prompt.key)
        )
        return list(result.scalars().all())

    async def update_by_key(self, key: str, content: str) -> Optional[Prompt]:
        await self.session.execute(
            update(Prompt)
            .where(Prompt.key == key)
            .values(content=content)
        )
        await self.session.commit()
        return await self.get_by_key(key)
