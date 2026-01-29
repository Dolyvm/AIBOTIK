"""Репозиторий для работы с мирами."""
from typing import Optional
from sqlalchemy import select

from shared.models import World
from .base import BaseRepository


class WorldRepository(BaseRepository[World]):
    model = World

    async def get_all_with_filter(self, tag: Optional[str] = None) -> list[World]:
        query = select(World)
        if tag:
            query = query.where(World.tags.any(tag))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_first_message(
        self,
        world_id: str,
        scenario_index: int,
        user_name: str
    ) -> str:
        world = await self.get_by_id(world_id)
        if not world:
            return ""

        scenarios = world.scenarios or []

        if scenario_index > 0 and scenario_index < len(scenarios):
            greeting = scenarios[scenario_index].get("intro", "")
        else:
            greeting = scenarios[0].get("intro", "") if scenarios else ""

        greeting = greeting.replace("{{user}}", user_name)
        return greeting
