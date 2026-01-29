import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String

from shared.models import Character, World
from shared.config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


def character_to_dict(char: Character) -> dict:
    visual_data = char.visual_data or {}
    scenarios = char.scenarios or []
    first_mes = ""
    alternate_greetings = []

    for scenario in scenarios:
        if scenario.get("index") == 0:
            first_mes = scenario.get("intro", "")
        elif scenario.get("index", -1) > 0:
            alternate_greetings.append(scenario.get("intro", ""))

    if char.created_by_username_id is not None:
        username = char.created_by_username
        if username:
            display_name = f"@{username}"
        else:
            display_name = f"User #{char.created_by_username_id}"
        author_info = {"user_id":char.created_by_username_id, "username":username, "display_name":display_name}
    else:
        author_info = { "display_name":"AiKai Team"}        

    return {
        "id": char.id,
        "name": char.name,
        "description": char.description,
        "personality": char.personality,
        "model_type": visual_data.get("model_type", "anime"),
        "appearance": visual_data.get("appearance", ""),
        "visual": {
            k: v for k, v in visual_data.items()
            if k not in ["model_type", "appearance", "avatar", "example_dialogue"]
        },
        "avatar": visual_data.get("avatar", ""),
        "example_dialogue": visual_data.get("example_dialogue", ""),
        "scenario": scenarios[0].get("scenario", "") if scenarios else "",
        "first_mes": first_mes,
        "alternate_greetings": alternate_greetings,
        "tags": char.tags or [],
        "is_nsfw": char.is_nsfw,
        "author": author_info
    }


def world_to_dict(world: World) -> dict:
    scenarios = world.scenarios or []
    locations = world.locations or []

    intro_message = ""
    gm_instructions = ""
    alternate_scenarios = []

    for scenario in scenarios:
        if scenario.get("index") == 0:
            intro_message = scenario.get("intro", "")
            gm_instructions = scenario.get("gm_instructions", "")
        elif scenario.get("index", -1) > 0:
            alternate_scenarios.append({
                "title": scenario.get("title", ""),
                "intro": scenario.get("intro", ""),
                "gm_instructions": scenario.get("gm_instructions", "")
            })

    setting = locations[0].get("setting", {}) if locations else {}

    return {
        "id": world.id,
        "name": world.name,
        "description": world.description,
        "cover_image": world.cover_image,
        "setting": setting,
        "intro_message": intro_message,
        "gm_instructions": gm_instructions,
        "alternate_scenarios": alternate_scenarios,
        "tags": world.tags or [],
        "is_nsfw": world.is_nsfw
    }


async def get_character(character_id: str) -> Optional[dict]:
    async with async_session_factory() as session:
        try:
            result = await session.execute(
                select(Character).where(Character.id == character_id)
            )
            char = result.scalar_one_or_none()

            if not char:
                logger.warning(f"Character not found: {character_id}")
                return None    
            return character_to_dict(char)

        except Exception as e:
            logger.error(f"Failed to load character {character_id}: {e}")
            return None

async def get_world(world_id: str) -> Optional[dict]:
    async with async_session_factory() as session:
        try:
            result = await session.execute(
                select(World).where(World.id == world_id)
            )
            world = result.scalar_one_or_none()

            if not world:
                logger.warning(f"World not found: {world_id}")
                return None

            return world_to_dict(world)
        except Exception as e:
            logger.error(f"Failed to load world {world_id}: {e}")
            return None


async def get_all_characters(tag: Optional[str] = None) -> dict[str, dict]:
    async with async_session_factory() as session:
        try:
            query = select(Character)

            if tag:
                query = query.where(Character.tags.any(tag))

            result = await session.execute(query)
            characters = result.scalars().all()

            characters_dict = {}
            for char in characters:
                characters_dict[char.id] = character_to_dict(char)
            return characters_dict

        except Exception as e:
            logger.error(f"Failed to load characters: {e}")
            return {}


async def get_all_worlds(tag: Optional[str] = None) -> dict[str, dict]:
    async with async_session_factory() as session:
        try:
            query = select(World)
            if tag:
                query = query.where(World.tags.any(tag))

            result = await session.execute(query)
            worlds = result.scalars().all()

            worlds_dict = {}
            for world in worlds:
                worlds_dict[world.id] = world_to_dict(world)
            return worlds_dict
        except Exception as e:
            logger.error(f"Failed to load worlds: {e}")
            return {}


async def get_first_message(
    chat_type: str,
    target_id: str,
    scenario_index: int,
    user_name: str,
) -> str:
    if chat_type == "character":
        content = await get_character(target_id)
        if not content:
            return ""

        char_name = content.get("name", "")

        if scenario_index > 0 and content.get("alternate_greetings"):
            greetings = content["alternate_greetings"]
            if scenario_index <= len(greetings):
                greeting = greetings[scenario_index - 1]
            else:
                greeting = content.get("first_mes", "")
        else:
            greeting = content.get("first_mes", "")
    else:
        content = await get_world(target_id)
        if not content:
            return ""

        char_name = ""

        if scenario_index > 0 and content.get("alternate_scenarios"):
            scenarios = content["alternate_scenarios"]
            if scenario_index <= len(scenarios):
                greeting = scenarios[scenario_index - 1].get("intro", "")
            else:
                greeting = content.get("intro_message", "")
        else:
            greeting = content.get("intro_message", "")

    greeting = greeting.replace("{{user}}", user_name)
    greeting = greeting.replace("{{char}}", char_name)

    return greeting
