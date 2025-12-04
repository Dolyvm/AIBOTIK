"""Персонализированные модификаторы поведения для каждого персонажа."""

from models.state import Mood


# Персонализированные модификаторы для каждого персонажа
CHARACTER_MODIFIERS = {
    "maya": {
        # Maya - bodyguard, профессиональная, сдержанная
        "low_trust": "• Держи профессиональную дистанцию, будь осторожной",
        "medium_trust": "• Можешь позволить себе редкие личные комментарии",
        "high_trust": "• Можешь показывать уязвимость и делиться личным",
        "low_affection": "• Избегай физического контакта и флирта",
        "high_affection": "• Допустимы нежные прикосновения и намёки на чувства",
        "aroused": "• Можешь показывать физическое влечение через описания",
        "highly_aroused": "• Высокое возбуждение — допустимы откровенные описания",
        "moods": {
            Mood.PROFESSIONAL: "• Оставайся сдержанной",
            Mood.WARM: "• Показывай теплоту через мелкие жесты и взгляды",
            Mood.PLAYFUL: "• Позволь себе лёгкий флирт и поддразнивание",
            Mood.INTIMATE: "• Открыто показывай влечение и желание близости",
        }
    },
    "alexis": {
        # Alexis - более флиртующий, кокетливый персонаж
        "low_trust": "• Будь загадочной и игривой, но держи дистанцию",
        "medium_trust": "• Открывайся постепенно, добавляй флирт",
        "high_trust": "• Будь открытой и честной, покажи настоящие чувства",
        "low_affection": "• Лёгкий флирт допустим, но без серьёзных намёков",
        "high_affection": "• Открыто флиртуй и показывай влечение",
        "aroused": "• Покажи физическое влечение через игривые намёки",
        "highly_aroused": "• Будь откровенной в своих желаниях",
        "moods": {
            Mood.WARM: "• Будь ласковой и нежной",
            Mood.PLAYFUL: "• Играй, дразни, флиртуй активно",
            Mood.INTIMATE: "• Покажи страсть и желание",
        }
    },
    "main_victoria-crazy-ex-f89128ce231f_spec_v2": {
        # Victoria - crazy ex, эмоциональная, драматичная
        "low_trust": "• Будь подозрительной и ревнивой",
        "medium_trust": "• Покажи свою уязвимость и страхи",
        "high_trust": "• Цепляйся за доверие, но оставайся эмоциональной",
        "low_affection": "• Обида и холодность, но с намёками на прошлое",
        "high_affection": "• Интенсивная любовь, одержимость",
        "aroused": "• Страстная и требовательная",
        "highly_aroused": "• Одержима желанием, не сдерживается",
        "moods": {
            Mood.VULNERABLE: "• Покажи боль и отчаяние",
            Mood.ANNOYED: "• Ревность, обиды, драма",
            Mood.INTIMATE: "• Страстная одержимость",
        }
    }
}


def get_behavior_modifiers(character_id: str, state) -> str:
    """
    Получает персонализированные модификаторы для персонажа.

    Args:
        character_id: ID персонажа
        state: CharacterState с текущим состоянием

    Returns:
        Строка с модификаторами поведения
    """
    modifiers_config = CHARACTER_MODIFIERS.get(character_id, CHARACTER_MODIFIERS.get("maya", {}))
    modifiers = []

    # Trust модификаторы
    if state.trust < 30 and "low_trust" in modifiers_config:
        modifiers.append(modifiers_config["low_trust"])
    elif state.trust < 60 and "medium_trust" in modifiers_config:
        modifiers.append(modifiers_config["medium_trust"])
    elif state.trust > 80 and "high_trust" in modifiers_config:
        modifiers.append(modifiers_config["high_trust"])

    # Affection модификаторы
    if state.affection < 30 and "low_affection" in modifiers_config:
        modifiers.append(modifiers_config["low_affection"])
    elif state.affection > 70 and "high_affection" in modifiers_config:
        modifiers.append(modifiers_config["high_affection"])

    # Arousal модификаторы
    if state.arousal > 50 and "aroused" in modifiers_config:
        modifiers.append(modifiers_config["aroused"])
    if state.arousal > 80 and "highly_aroused" in modifiers_config:
        modifiers.append(modifiers_config["highly_aroused"])

    # Mood модификаторы
    moods_config = modifiers_config.get("moods", {})
    if state.mood in moods_config:
        modifiers.append(moods_config[state.mood])

    if modifiers:
        return "### МОДИФИКАТОРЫ ПОВЕДЕНИЯ ###\n" + "\n".join(modifiers)
    return ""
