"""Начальные значения состояния для каждого сценария персонажей."""

from models.state import Mood


# Начальные значения для каждого сценария каждого персонажа
SCENARIO_INITIAL_STATES = {
    "maya": {
        0: {"trust": 25, "affection": 10, "arousal": 0, "comfort": 30, "mood": Mood.ANNOYED},        # Основной - шторм, злая
        1: {"trust": 50, "affection": 30, "arousal": 10, "comfort": 40, "mood": Mood.PROFESSIONAL},  # После боя
        2: {"trust": 15, "affection": 5, "arousal": 5, "comfort": 10, "mood": Mood.PROFESSIONAL},    # Трущобы, настороженная
        3: {"trust": 40, "affection": 20, "arousal": 5, "comfort": 35, "mood": Mood.WARM},           # Тренировка, теплее
        4: {"trust": 45, "affection": 35, "arousal": 15, "comfort": 50, "mood": Mood.VULNERABLE},    # Озеро, уязвима
        5: {"trust": 60, "affection": 50, "arousal": 10, "comfort": 30, "mood": Mood.ANNOYED},       # После ссоры
    },
    "alexis": {
        0: {"trust": 30, "affection": 20, "arousal": 10, "comfort": 40, "mood": Mood.PLAYFUL},  # Основной - игривая
        1: {"trust": 30, "affection": 20, "arousal": 10, "comfort": 40, "mood": Mood.PLAYFUL},  # Братик - игривая
        2: {"trust": 30, "affection": 20, "arousal": 10, "comfort": 40, "mood": Mood.PLAYFUL},  # Сестренка - игривая
    },
    "main_victoria-crazy-ex-f89128ce231f_spec_v2": {
        0: {"trust": 70, "affection": 80, "arousal": 40, "comfort": 20, "mood": Mood.VULNERABLE},  # Crazy ex - отчаянная
    }
}


def get_initial_state(character_id: str, scenario_index: int) -> dict:
    """
    Получает начальное состояние для персонажа и сценария.

    Args:
        character_id: ID персонажа
        scenario_index: Индекс сценария (0 = основной, 1+ = альтернативные)

    Returns:
        Словарь с начальными значениями trust, affection, arousal, comfort
    """
    # Получаем сценарии для персонажа
    character_scenarios = SCENARIO_INITIAL_STATES.get(
        character_id,
        SCENARIO_INITIAL_STATES.get("maya", {})
    )

    # Получаем значения для конкретного сценария или используем основной
    return character_scenarios.get(scenario_index, character_scenarios.get(0, {
        "trust": 25,
        "affection": 10,
        "arousal": 0,
        "comfort": 30,
        "mood": Mood.PROFESSIONAL
    }))
