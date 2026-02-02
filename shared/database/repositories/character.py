"""Репозиторий для работы с персонажами."""
from typing import Optional
from sqlalchemy import select

from shared.models import Character
from .base import BaseRepository


class CharacterRepository(BaseRepository[Character]):
    model = Character

    async def get_all_with_filter(self, tag: Optional[str] = None) -> list[Character]:
        query = select(Character)
        if tag:
            query = query.where(Character.tags.any(tag))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_first_message(
        self,
        character_id: str,
        scenario_index: int,
        user_name: str
    ) -> str:
        character = await self.get_by_id(character_id)
        if not character:
            return ""

        scenarios = character.scenarios or []
        char_name = character.name

        if scenario_index > 0:
            alt_index = scenario_index - 1
            if alt_index < len(scenarios) - 1:
                greeting = scenarios[scenario_index].get("intro", "")
            else:
                greeting = scenarios[0].get("intro", "") if scenarios else ""
        else:
            greeting = scenarios[0].get("intro", "") if scenarios else ""

        greeting = greeting.replace("{{user}}", user_name)
        greeting = greeting.replace("{{char}}", char_name)
        return greeting
