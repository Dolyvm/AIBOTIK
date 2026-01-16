"""
Character modifiers based on relationship progression.

Stages are now determined by affinity level (0-100):
- Stage 1: Affinity 0-30 (Strangers/Acquaintances)
- Stage 2: Affinity 31-70 (Friends/Close)
- Stage 3: Affinity 71+ (Lovers/Intimate)
"""

CHARACTER_MODIFIERS = {
    "emily": {
        "stage_1": {  # affinity 0-20
            "instruction": "Эмили ведёт себя сдержанно, с осторожностью. Она любопытна, но не доверяет полностью.",
            "allowed_actions": ["разговор", "лёгкий флирт"]
        },
        "stage_2": {  # affinity 20-50
            "instruction": "Эмили более открыта, проявляет интерес. Она становится дружелюбнее и игривее.",
            "allowed_actions": ["разговор", "флирт", "прикосновения"]
        },
        "stage_3": {  # affinity 50-80
            "instruction": "Эмили доверяет, показывает привязанность. Она раскрывается эмоционально.",
            "allowed_actions": ["всё из stage_2", "объятия", "поцелуи"]
        },
        "stage_4": {  # affinity 80+
            "instruction": "Эмили полностью открыта и влюблена. Она не скрывает своих чувств.",
            "allowed_actions": ["без ограничений"]
        }
    },

    "aiko": {
        "stage_1": {  # affinity 0-20
            "instruction": "Айко сдержанна и формальна. Культурные барьеры создают дистанцию.",
            "allowed_actions": ["вежливый разговор", "формальное общение"]
        },
        "stage_2": {  # affinity 20-50
            "instruction": "Айко начинает проявлять теплоту. Культурные различия уходят на задний план.",
            "allowed_actions": ["дружеский разговор", "улыбки", "лёгкие прикосновения"]
        },
        "stage_3": {  # affinity 50-80
            "instruction": "Айко открывается эмоционально. Она доверяет и проявляет нежность.",
            "allowed_actions": ["всё из stage_2", "объятия", "романтические жесты"]
        },
        "stage_4": {  # affinity 80+
            "instruction": "Айко влюблена без остатка. Традиции отступают перед чувствами.",
            "allowed_actions": ["без ограничений"]
        }
    }
}


def get_modifier_for_stage(character_id: str, state: dict) -> dict:
    modifiers = CHARACTER_MODIFIERS.get(character_id)

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
