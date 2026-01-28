from shared.constants import get_modifier_for_stage
from shared.services.prompt_service import get_prompt


def _get_common_style_guide() -> str:
    return get_prompt("common_style_guide")


def _get_meta_instruction() -> str:
    return get_prompt("meta_instruction")

def _get_character_behavior(affinity: int, arousal: int) -> str:
    instruction = ""

    if affinity < 20:
        instruction += get_prompt("behavior_affinity_cold")
    elif affinity < 50:
        instruction += get_prompt("behavior_affinity_neutral")
    elif affinity < 80:
        instruction += get_prompt("behavior_affinity_warm")
    else:
        instruction += get_prompt("behavior_affinity_love")

    if arousal > 50:
        instruction += get_prompt("behavior_arousal_high")

    return instruction


def build_character_prompt(
        character: dict,
        chat,
        summary: str = "",
        user_name: str = "User"
) -> str:
    affinity = chat.affinity
    arousal = chat.arousal
    mood = chat.current_mood

    behavior_instruction = _get_character_behavior(affinity, arousal)

    char_id = character.get("id", "")
    state_dict = {
        "affinity": chat.affinity,
        "arousal": chat.arousal,
        "mood": chat.current_mood,
        "location": chat.current_location
    }
    modifier = get_modifier_for_stage(char_id, state_dict)

    modifier_text = ""
    if modifier:
        modifier_text = f"\n\n### ТЕКУЩАЯ СТАДИЯ ОТНОШЕНИЙ ###\n{modifier['instruction']}"
        if modifier.get('allowed_actions'):
            modifier_text += f"\nДопустимые действия: {', '.join(modifier['allowed_actions'])}"

    char_name = character["name"]
    description = character["description"].replace("{{user}}", user_name).replace("{{char}}", char_name)
    personality = character["personality"].replace("{{user}}", user_name).replace("{{char}}", char_name)
    scenario = character["scenario"].replace("{{user}}", user_name).replace("{{char}}", char_name)

    template = get_prompt("character_prompt_template")
    prompt = template.format(
        char_name=char_name,
        description=description,
        personality=personality,
        scenario=scenario,
        summary=summary if summary else "История только начинается.",
        affinity=affinity,
        arousal=arousal,
        mood=mood,
        behavior_instruction=behavior_instruction,
        modifier_text=modifier_text,
        common_style_guide=_get_common_style_guide(),
        meta_instruction=_get_meta_instruction(),
    )
    return prompt


def build_world_prompt(world: dict, summary: str = "", user_name: str = "Игрок") -> str:
    """
    Build system prompt for world/Game Master with literary style.
    """
    template = get_prompt("world_prompt_template")
    prompt = template.format(
        world_name=world['name'],
        user_name=user_name,
        world_description=world['description'],
        summary=summary if summary else "Приключение начинается.",
        common_style_guide=_get_common_style_guide(),
        meta_instruction=_get_meta_instruction(),
    )
    return prompt


def build_player_prompt(
    character_name: str,
    last_character_message: str,
    chat_history: list,
    user_name: str = "User"
) -> str:
    user_messages = [msg for msg in chat_history if msg['role'] == 'user']
    style_examples = "\n".join([f"- {msg['content']}" for msg in user_messages[-3:]])

    prompt_template = get_prompt("player_prompt")
    prompt = prompt_template.format(
        user_name=user_name,
        character_name=character_name,
        last_character_message=last_character_message,
        style_examples=style_examples if style_examples else "История только начинается. Создай естественное первое действие."
    )
    return prompt
