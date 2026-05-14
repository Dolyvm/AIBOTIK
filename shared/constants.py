from shared.services.prompt_service import get_prompt
from shared.services.cache import get_cache

HEAT_LEVEL_DEFAULTS = {
    0: {"affinity": 0, "arousal": 0},
    1: {"affinity": 30, "arousal": 10},
    2: {"affinity": 60, "arousal": 40},
    3: {"affinity": 90, "arousal": 70},
}

HEAT_LEVEL_CONTEXT = {
    0: "медленное знакомство, дистанция и осторожность",
    1: "лёгкий флирт, интерес и первые признаки доверия",
    2: "быстрое сближение, тепло и явная взаимная симпатия",
    3: "высокая близость, смелый флирт и сильное притяжение",
}


def normalize_heat_level(value) -> int:
    try:
        heat_level = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(3, heat_level))


def infer_heat_level_from_affinity(affinity: int) -> int:
    if affinity >= 80:
        return 3
    if affinity >= 50:
        return 2
    if affinity >= 20:
        return 1
    return 0


def get_heat_level(state) -> int:
    if state is None:
        return 0

    if isinstance(state, dict):
        if "heat_level" in state:
            return normalize_heat_level(state.get("heat_level"))
        state_meta = state.get("state_meta") or {}
        if isinstance(state_meta, dict) and "heat_level" in state_meta:
            return normalize_heat_level(state_meta.get("heat_level"))
        if "affinity" in state:
            return infer_heat_level_from_affinity(state.get("affinity", 0))
        return 0

    state_meta = getattr(state, "state_meta", None) or {}
    if isinstance(state_meta, dict) and "heat_level" in state_meta:
        return normalize_heat_level(state_meta.get("heat_level"))

    return infer_heat_level_from_affinity(getattr(state, "affinity", 0))


def get_heat_context(heat_level: int) -> str:
    heat_level = normalize_heat_level(heat_level)
    return f"heat_level {heat_level}: {HEAT_LEVEL_CONTEXT[heat_level]}"


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

    stage_num = get_heat_level(state) + 1
    return modifiers.get(f"stage_{stage_num}")
