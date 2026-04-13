from typing import Optional
from sqlalchemy import select, func, delete
from sqlalchemy.exc import IntegrityError

from shared.models import CharacterLike
from .base import BaseRepository


class LikeRepository(BaseRepository[CharacterLike]):
    model = CharacterLike

    async def get_like(self, user_id: int, character_id: str) -> Optional[CharacterLike]:
        result = await self.session.execute(
            select(CharacterLike).where(
                CharacterLike.user_id == user_id,
                CharacterLike.character_id == character_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_like(self, user_id: int, character_id: str) -> CharacterLike:
        like = CharacterLike(user_id=user_id, character_id=character_id)
        self.session.add(like)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_like(user_id, character_id)
            if existing:
                return existing
            raise
        return like

    async def remove_like(self, user_id: int, character_id: str) -> bool:
        result = await self.session.execute(
            delete(CharacterLike).where(
                CharacterLike.user_id == user_id,
                CharacterLike.character_id == character_id,
            )
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def get_like_count(self, character_id: str) -> int:
        result = await self.session.execute(
            select(func.count(CharacterLike.user_id)).where(
                CharacterLike.character_id == character_id
            )
        )
        return int(result.scalar() or 0)

    async def get_like_counts_batch(self, character_ids: list[str]) -> dict[str, int]:
        if not character_ids:
            return {}
        result = await self.session.execute(
            select(CharacterLike.character_id, func.count(CharacterLike.user_id))
            .where(CharacterLike.character_id.in_(character_ids))
            .group_by(CharacterLike.character_id)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def get_liked_character_ids(self, user_id: int, character_ids: list[str]) -> set[str]:
        if not character_ids:
            return set()
        result = await self.session.execute(
            select(CharacterLike.character_id).where(
                CharacterLike.user_id == user_id,
                CharacterLike.character_id.in_(character_ids),
            )
        )
        return {row[0] for row in result.all()}
