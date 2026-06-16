import logging
import re

from shared.constants import (
    HEAT_LEVEL_DEFAULTS,
    get_heat_context,
    get_heat_level,
    get_modifier_for_stage,
)
from shared.services.prompt_service import DEFAULT_PROMPTS, get_prompt


PLAYER_OUTPUT_GUARD = """
Контроль автоответа: только короткое сообщение игрока от первого лица на русском.
Не пиши за персонажа и не повторяй прошлые сообщения игрока дословно.
Без JSON, <meta>, markdown, заголовков и role labels.
"""


async def _get_common_style_guide() -> str:
    return await get_prompt("common_style_guide")


def _get_gender_identity_instruction(gender: str) -> str:
    if gender == "male":
        return (
            "Пол персонажа: мужчина. Описывай его только в мужском роде; "
            "не используй женский род для действий, мыслей и эмоций персонажа."
        )

    return (
        "Пол персонажа: женщина. Описывай её только в женском роде; "
        "не используй мужской род для действий, мыслей и эмоций персонажа."
    )


async def _get_meta_instruction(allow_nsfw: bool = True) -> str:
    key = "meta_instruction" if allow_nsfw else "meta_instruction_sfw"
    try:
        prompt = await get_prompt(key)
        if _is_legacy_meta_instruction(prompt):
            logging.warning("Legacy meta prompt detected for '%s', using compact default", key)
            return DEFAULT_PROMPTS[key]
        return prompt
    except KeyError:
        if not allow_nsfw:
            logging.warning(f"SFW prompt '{key}' not found, falling back to default")
            return await get_prompt("meta_instruction")
        raise


def _is_legacy_meta_instruction(prompt: str) -> bool:
    return (
        '"mood": ...' in prompt
        or '"thought": ...' in prompt
        or "//" in prompt
        or re.search(r'"(?:affinity_change|arousal_change)"\s*:', prompt) is not None
    )

async def _get_character_behavior(heat_level: int, allow_nsfw: bool = True, gender: str = "female") -> str:
    instruction = ""
    is_male = gender == "male"

    if heat_level <= 0:
        instruction += await get_prompt("behavior_affinity_cold")
    elif heat_level == 1:
        instruction += await get_prompt("behavior_affinity_neutral")
    elif heat_level == 2:
        instruction += await get_prompt("behavior_affinity_warm")
    else:
        key = "behavior_affinity_love_male" if is_male else "behavior_affinity_love"
        try:
            instruction += await get_prompt(key)
        except KeyError:
            instruction += await get_prompt("behavior_affinity_love")

    if heat_level >= 3:
        if allow_nsfw:
            key = "behavior_arousal_high_male" if is_male else "behavior_arousal_high"
            try:
                instruction += await get_prompt(key)
            except KeyError:
                instruction += await get_prompt("behavior_arousal_high")
        else:
            try:
                instruction += await get_prompt("behavior_arousal_high_sfw")
            except KeyError:
                logging.warning("SFW arousal prompt not found, using default")
                instruction += await get_prompt("behavior_arousal_high")

    return instruction

async def build_character_prompt(
        character: dict,
        chat,
        summary: str = "",
        user_name: str = "User",
        allow_nsfw: bool = True
) -> str:
    heat_level = get_heat_level(chat)
    legacy_state = HEAT_LEVEL_DEFAULTS[heat_level]
    affinity = legacy_state["affinity"]
    arousal = legacy_state["arousal"]
    mood = chat.current_mood

    gender = character.get("visual", {}).get("gender", "female")
    behavior_instruction = await _get_character_behavior(heat_level, allow_nsfw, gender=gender)

    char_id = character.get("id", "")
    state_dict = {
        "heat_level": heat_level,
        "affinity": affinity,
        "arousal": arousal,
        "mood": chat.current_mood,
        "location": chat.current_location
    }
    modifier = await get_modifier_for_stage(char_id, state_dict, allow_nsfw)

    modifier_text = ""
    if modifier:
        modifier_text = f"\n\n### ТЕКУЩАЯ СТАДИЯ ОТНОШЕНИЙ ###\n{modifier['instruction']}"
        if modifier.get('allowed_actions'):
            modifier_text += f"\nДопустимые действия: {', '.join(modifier['allowed_actions'])}"

    char_name = character["name"]
    description = character["description"].replace("{{user}}", user_name).replace("{{char}}", char_name)
    personality = character["personality"].replace("{{user}}", user_name).replace("{{char}}", char_name)
    scenario = character["scenario"].replace("{{user}}", user_name).replace("{{char}}", char_name)
    preferences = character["visual"].get("llm_settings", {}).get("preferences")
    if not preferences:
        preferences = "Не указано."
    else:
        preferences = ", ".join(preferences)

    template = await get_prompt("character_prompt_template")
    prompt = template.format(
        char_name=char_name,
        user_name=user_name,
        description=description,
        personality=personality,
        scenario=scenario,
        summary=summary if summary else "История только начинается.",
        location=chat.current_location or "не определена",
        affinity=affinity,
        arousal=arousal,
        heat_level=heat_level,
        heat_context=get_heat_context(heat_level),
        mood=mood,
        behavior_instruction=behavior_instruction,
        modifier_text=modifier_text,
        common_style_guide=await _get_common_style_guide(),
        meta_instruction=await _get_meta_instruction(allow_nsfw),
        relationship_role=character["visual"].get("llm_settings", {}).get("relationship_role", "Не указано"),
        preferences=preferences
    )
    prompt = f"{_get_gender_identity_instruction(gender)}\n\n{prompt}"

    if not allow_nsfw:
        try:
            sfw_restriction = await get_prompt("sfw_content_restriction")
            prompt += f"\n\n{sfw_restriction}"
        except KeyError:
            logging.warning("SFW content restriction prompt not found")

    return prompt

async def build_world_prompt(
        world: dict,
        summary: str = "",
        user_name: str = "Игрок",
        allow_nsfw: bool = True,
        location: str = "",
        scenario_index: int = 0
) -> str:
    scenario_context = _build_world_scenario_context(world, scenario_index)
    template = await get_prompt("world_prompt_template")
    prompt = template.format(
        world_name=world['name'],
        user_name=user_name,
        world_description=world['description'],
        summary=summary if summary else "Приключение начинается.",
        location=location or "не определена",
        common_style_guide=await _get_common_style_guide(),
        meta_instruction=await _get_meta_instruction(allow_nsfw),
    )
    if scenario_context:
        prompt += f"\n\nВЫБРАННЫЙ СЦЕНАРИЙ\n{scenario_context}"

    if not allow_nsfw:
        try:
            sfw_restriction = await get_prompt("sfw_content_restriction")
            prompt += f"\n\n{sfw_restriction}"
        except KeyError:
            logging.warning("SFW content restriction prompt not found")

    return prompt


def _build_world_scenario_context(world: dict, scenario_index: int = 0) -> str:
    if scenario_index > 0:
        scenarios = world.get("alternate_scenarios") or []
        selected = scenarios[scenario_index - 1] if scenario_index <= len(scenarios) else {}
        title = selected.get("title") or f"Сценарий {scenario_index}"
        intro = selected.get("intro", "")
        gm_instructions = selected.get("gm_instructions", "")
    else:
        title = world.get("main_scenario_title") or "Основной"
        intro = world.get("intro_message", "")
        gm_instructions = world.get("gm_instructions", "")

    parts = [f"Название: {title}"]
    if gm_instructions:
        parts.append(f"Инструкции сценария:\n{gm_instructions}")
    if intro:
        parts.append(
            "Стартовое сообщение сценария уже было показано игроку. "
            f"Не повторяй его дословно, но учитывай заданную им стартовую сцену:\n{intro}"
        )
    return "\n\n".join(parts)

async def build_player_prompt(
    character_name: str,
    last_character_message: str,
    chat_history: list,
    user_name: str = "User"
) -> str:
    user_messages = [msg for msg in chat_history if msg['role'] == 'user']
    style_examples = "\n".join([f"- {msg['content']}" for msg in user_messages[-3:]])

    prompt_template = await get_prompt("player_prompt")
    prompt = prompt_template.format(
        user_name=user_name,
        character_name=character_name,
        last_character_message=last_character_message,
        style_examples=style_examples if style_examples else "История только начинается. Создай естественное первое действие."
    )
    return f"{prompt.rstrip()}\n\n{PLAYER_OUTPUT_GUARD.strip()}\n"
