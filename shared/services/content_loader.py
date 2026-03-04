import logging
from typing import Optional

from shared.models import Character, World
from shared.database import get_session
from shared.database.repositories import CharacterRepository, WorldRepository
from shared.services.cache import get_cache

logger = logging.getLogger(__name__)

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

    scenarios_full = [
        {
            "index": s.get("index", 0),
            "scenario": s.get("scenario", ""),
            "intro": s.get("intro", ""),
            "heat_level": s.get("heat_level", 0),
        }
        for s in scenarios
    ]

    return {
        "id": char.id,
        "name": char.name,
        "short_description": char.short_description or "",
        "is_public": char.is_public,
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
        "scenarios_full": scenarios_full,
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

    if world.created_by_username_id is not None:
        username = world.created_by_username
        if username:
            display_name = f"@{username}"
        else:
            display_name = f"User #{world.created_by_username_id}"
        author_info = {"user_id": world.created_by_username_id, "username": username, "display_name": display_name}
    else:
        author_info = {"display_name": "AiKai Team"}

    return {
        "id": world.id,
        "name": world.name,
        "short_description": world.short_description or "",
        "description": world.description,
        "cover_image": world.cover_image,
        "setting": setting,
        "intro_message": intro_message,
        "gm_instructions": gm_instructions,
        "alternate_scenarios": alternate_scenarios,
        "tags": world.tags or [],
        "is_nsfw": world.is_nsfw,
        "author": author_info
    }

async def get_character(character_id: str) -> Optional[dict]:
    cache = get_cache()
    if cache:
        cached = await cache.get_character(character_id)
        if cached:
            logger.debug(f"Character {character_id} loaded from cache")
            return cached

    async with get_session() as session:
        try:
            repo = CharacterRepository(session)
            char = await repo.get_by_id(character_id)
            if not char:
                logger.warning(f"Character not found: {character_id}")
                return None
            result = character_to_dict(char)

            if cache:
                await cache.set_character(character_id, result)

            return result
        except Exception as e:
            logger.error(f"Failed to load character {character_id}: {e}")
            return None

async def get_world(world_id: str) -> Optional[dict]:
    cache = get_cache()
    if cache:
        cached = await cache.get_world(world_id)
        if cached:
            logger.debug(f"World {world_id} loaded from cache")
            return cached

    async with get_session() as session:
        try:
            repo = WorldRepository(session)
            world = await repo.get_by_id(world_id)
            if not world:
                logger.warning(f"World not found: {world_id}")
                return None
            result = world_to_dict(world)

            if cache:
                await cache.set_world(world_id, result)

            return result
        except Exception as e:
            logger.error(f"Failed to load world {world_id}: {e}")
            return None

async def get_all_characters(tag: Optional[str] = None) -> dict[str, dict]:
    cache = get_cache()
    if cache and tag is None:
        cached = await cache.get_all_characters()
        if cached:
            logger.debug("All characters loaded from cache")
            return {char["id"]: char for char in cached}

    async with get_session() as session:
        try:
            repo = CharacterRepository(session)
            characters = await repo.get_all_with_filter(tag)
            result = {char.id: character_to_dict(char) for char in characters}

            if cache and tag is None:
                await cache.set_all_characters(list(result.values()))

            return result
        except Exception as e:
            logger.error(f"Failed to load characters: {e}")
            return {}

async def get_all_worlds(tag: Optional[str] = None) -> dict[str, dict]:
    cache = get_cache()
    if cache and tag is None:
        cached = await cache.get_all_worlds()
        if cached:
            logger.debug("All worlds loaded from cache")
            return {world["id"]: world for world in cached}

    async with get_session() as session:
        try:
            repo = WorldRepository(session)
            worlds = await repo.get_all_with_filter(tag)
            result = {world.id: world_to_dict(world) for world in worlds}

            if cache and tag is None:
                await cache.set_all_worlds(list(result.values()))

            return result
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
