from shared.services.prompt_service import get_prompt
from shared.services.cache import get_cache

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

async def _load_character_modifiers(character_id: str) -> dict:
    stages = {}
    for stage_num in range(1, 5):
        stage_key = f"stage_{stage_num}"
        prompt_key = f"character_modifiers_{character_id}_{stage_key}"
        try:
            prompt_value = await get_prompt(prompt_key)
            stages[stage_key] = _parse_modifier(prompt_value)
        except KeyError:
            return {}
    return stages

async def _get_character_modifiers(character_id: str) -> dict:
    cache = get_cache()

    if cache:
        cached = await cache.get_character_modifiers(character_id)
        if cached:
            return cached

    modifiers = await _load_character_modifiers(character_id)

    if cache and modifiers:
        await cache.set_character_modifiers(character_id, modifiers)

    return modifiers

async def invalidate_character_modifiers_cache():
    cache = get_cache()
    if cache:
        await cache.invalidate_character_modifiers()

async def get_modifier_for_stage(character_id: str, state: dict, allow_nsfw: bool = True) -> dict:
    modifiers = await _get_character_modifiers(character_id)

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
