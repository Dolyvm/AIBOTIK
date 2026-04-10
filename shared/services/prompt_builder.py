import logging

from shared.constants import get_modifier_for_stage
from shared.services.prompt_service import get_prompt

async def _get_common_style_guide() -> str:
    return await get_prompt("common_style_guide")

async def _get_meta_instruction(allow_nsfw: bool = True) -> str:
    key = "meta_instruction" if allow_nsfw else "meta_instruction_sfw"
    try:
        prompt = await get_prompt(key)
        return prompt
    except KeyError:
        if not allow_nsfw:
            logging.warning(f"SFW prompt '{key}' not found, falling back to default")
            return await get_prompt("meta_instruction")
        raise

async def _get_character_behavior(affinity: int, arousal: int, allow_nsfw: bool = True, gender: str = "female") -> str:
    instruction = ""
    is_male = gender == "male"

    if affinity < 20:
        instruction += await get_prompt("behavior_affinity_cold")
    elif affinity < 50:
        instruction += await get_prompt("behavior_affinity_neutral")
    elif affinity < 80:
        instruction += await get_prompt("behavior_affinity_warm")
    else:
        key = "behavior_affinity_love_male" if is_male else "behavior_affinity_love"
        try:
            instruction += await get_prompt(key)
        except KeyError:
            instruction += await get_prompt("behavior_affinity_love")

    if arousal > 50:
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
    affinity = chat.affinity
    arousal = chat.arousal
    mood = chat.current_mood

    gender = character.get("visual", {}).get("gender", "female")
    behavior_instruction = await _get_character_behavior(affinity, arousal, allow_nsfw, gender=gender)

    char_id = character.get("id", "")
    state_dict = {
        "affinity": chat.affinity,
        "arousal": chat.arousal,
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
        affinity=affinity,
        arousal=arousal,
        mood=mood,
        behavior_instruction=behavior_instruction,
        modifier_text=modifier_text,
        common_style_guide=await _get_common_style_guide(),
        meta_instruction=await _get_meta_instruction(allow_nsfw),
        relationship_role=character["visual"].get("llm_settings", {}).get("relationship_role", "Не указано"),
        preferences=preferences
    )

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
        allow_nsfw: bool = True
) -> str:
    template = await get_prompt("world_prompt_template")
    prompt = template.format(
        world_name=world['name'],
        user_name=user_name,
        world_description=world['description'],
        summary=summary if summary else "Приключение начинается.",
        common_style_guide=await _get_common_style_guide(),
        meta_instruction=await _get_meta_instruction(allow_nsfw),
    )

    if not allow_nsfw:
        try:
            sfw_restriction = await get_prompt("sfw_content_restriction")
            prompt += f"\n\n{sfw_restriction}"
        except KeyError:
            logging.warning("SFW content restriction prompt not found")

    return prompt

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
    return prompt
