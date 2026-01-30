from shared.services.prompt_service import get_prompt

def _parse_modifier(prompt_value: str) -> dict:
    parts = prompt_value.split("|")
    if len(parts) == 2:
        instruction = parts[0].strip()
        actions_str = parts[1].strip()
        allowed_actions = [a.strip() for a in actions_str.split(",")]
        return {
            "instruction": instruction,
            "allowed_actions": allowed_actions
        }
    return {"instruction": prompt_value, "allowed_actions": []}


def _load_character_modifiers() -> dict:
    return {
        "emily": {
            "stage_1": _parse_modifier(get_prompt("character_modifiers_emily_stage_1")),
            "stage_2": _parse_modifier(get_prompt("character_modifiers_emily_stage_2")),
            "stage_3": _parse_modifier(get_prompt("character_modifiers_emily_stage_3")),
            "stage_4": _parse_modifier(get_prompt("character_modifiers_emily_stage_4")),
        },
        "aiko": {
            "stage_1": _parse_modifier(get_prompt("character_modifiers_aiko_stage_1")),
            "stage_2": _parse_modifier(get_prompt("character_modifiers_aiko_stage_2")),
            "stage_3": _parse_modifier(get_prompt("character_modifiers_aiko_stage_3")),
            "stage_4": _parse_modifier(get_prompt("character_modifiers_aiko_stage_4")),
        }
    }


_CHARACTER_MODIFIERS = None


def _get_character_modifiers() -> dict:
    global _CHARACTER_MODIFIERS
    if _CHARACTER_MODIFIERS is None:
        _CHARACTER_MODIFIERS = _load_character_modifiers()
    return _CHARACTER_MODIFIERS


def invalidate_character_modifiers_cache():
    global _CHARACTER_MODIFIERS
    _CHARACTER_MODIFIERS = None


def get_modifier_for_stage(character_id: str, state: dict, allow_nsfw: bool = True) -> dict:
    modifiers = _get_character_modifiers().get(character_id)

    if not modifiers:
        return None

    affinity = state.get("affinity", 0)

    if affinity < 20:
        return modifiers.get("stage_1")
    elif affinity < 50:
        return modifiers.get("stage_2")
    elif affinity < 80:
        return modifiers.get("stage_3")
    else:
        return modifiers.get("stage_4")
