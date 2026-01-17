import json
import logging
from functools import lru_cache
from typing import Optional

from shared.config import CONTENT_BASE_PATH

logger = logging.getLogger(__name__)

@lru_cache(maxsize=32)
def get_character(character_id: str) -> Optional[dict]:
    char_path = CONTENT_BASE_PATH / "characters" / f"{character_id}.json"
    if not char_path.exists():
        return None
    try:
        with open(char_path, encoding='utf-8') as file:
            char = json.load(file)
    except Exception as e:
        print(f"Failed to parse {char_path}: {e}")
        return None

    char["id"] = character_id  
    return char


@lru_cache(maxsize=32)
def get_world(world_id: str) -> Optional[dict]:
    world_path = CONTENT_BASE_PATH / "worlds" / f"{world_id}.json"
    if not world_path.exists():
        return None

    try:
        with open(world_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load {world_path}: {e}")
        return None


def get_all_characters() -> dict[str, dict]:
    characters = {}
    chars_dir = CONTENT_BASE_PATH / "characters"

    for json_file in chars_dir.glob("*.json"):
        char_id = json_file.stem
        try:
            char_data = get_character(char_id)
            if char_data:
                characters[char_id] = char_data
                logger.info(f"Loaded character: {char_id}")
        except Exception as e:
            logger.error(f"Failed to load character {char_id}: {e}")

    logger.info(f"Total characters loaded: {len(characters)}")
    return characters


def get_all_worlds() -> dict[str, dict]:
    """Загружает все миры"""
    worlds = {}
    worlds_dir = CONTENT_BASE_PATH / "worlds"

    if not worlds_dir.exists():
        return worlds

    for json_file in worlds_dir.glob("*.json"):
        try:
            with open(json_file, encoding="utf-8") as f:
                world = json.load(f)
                worlds[world["id"]] = world
        except Exception as e:
            print(f"Failed to load {json_file}: {e}")

    return worlds


def get_first_message(
    chat_type: str,
    target_id: str,
    scenario_index: int,
    user_name: str,
) -> str:
    """Получает первое сообщение для чата с заменой плейсхолдеров"""
    if chat_type == "character":
        content = get_character(target_id)
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
        content = get_world(target_id)
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
