"""Анализатор сообщений для обновления состояния персонажа."""

import re
from typing import List, Tuple

from models.state import CharacterState, StateUpdate, Mood


class StateAnalyzer:
    """Анализирует сообщения и определяет изменения состояния персонажа."""

    # Паттерны для позитивных взаимодействий (доверие)
    TRUST_POSITIVE_PATTERNS: List[Tuple[str, int]] = [
        (r"спасибо|благодар", 3),
        (r"доверяю|верю тебе", 5),
        (r"защит|спас", 4),
        (r"помо[гч]|поддерж", 3),
        (r"понима", 2),
    ]

    # Паттерны для позитивных взаимодействий (привязанность)
    AFFECTION_POSITIVE_PATTERNS: List[Tuple[str, int]] = [
        (r"красив|привлекат|нрав", 4),
        (r"скучал|скучаю", 5),
        (r"обним|прижим|прикос", 6),
        (r"поцелу", 10),
        (r"люблю|любовь", 8),
        (r"мил|нежн", 3),
    ]

    # Паттерны для возбуждения (arousal)
    AROUSAL_PATTERNS: List[Tuple[str, int]] = [
        (r"поцелу|целу", 15),
        (r"прикос|касан|глад", 10),
        (r"раздев|одежд", 20),
        (r"тело|кожа|губы", 8),
        (r"хочу тебя|желаю", 25),
        (r"сексуальн|возбужд", 20),
    ]

    # Паттерны для негативных взаимодействий
    NEGATIVE_PATTERNS: List[Tuple[str, int, int]] = [
        (r"злюсь|бесит|раздраж", -5, -5),
        (r"уйди|отстань|достал", -8, -10),
        (r"не доверяю", -15, 0),
        (r"грубо|обид", -10, -5),
        (r"ненавижу|терпеть не могу", -20, -15),
    ]

    def analyze_user_message(self, message: str, current_state: CharacterState) -> StateUpdate:
        """
        Анализирует сообщение пользователя и определяет изменения состояния.

        Args:
            message: Текст сообщения пользователя
            current_state: Текущее состояние персонажа

        Returns:
            StateUpdate с изменениями
        """
        message_lower = message.lower()
        update = StateUpdate()

        # Проверяем позитивные паттерны (доверие)
        for pattern, delta in self.TRUST_POSITIVE_PATTERNS:
            if re.search(pattern, message_lower):
                update.trust_delta += delta

        # Проверяем позитивные паттерны (привязанность)
        for pattern, delta in self.AFFECTION_POSITIVE_PATTERNS:
            if re.search(pattern, message_lower):
                update.affection_delta += delta

        # Проверяем паттерны возбуждения
        for pattern, delta in self.AROUSAL_PATTERNS:
            if re.search(pattern, message_lower):
                update.arousal_delta += delta

        # Проверяем негативные паттерны
        for pattern, trust_d, affect_d in self.NEGATIVE_PATTERNS:
            if re.search(pattern, message_lower):
                update.trust_delta += trust_d
                update.affection_delta += affect_d

        # Определяем флаги событий
        if re.search(r"прикос|касан|обним", message_lower) and not current_state.first_touch:
            update.flags_to_set.append("first_touch")
            update.event_to_remember = "Первое физическое прикосновение"

        if re.search(r"поцелу", message_lower) and not current_state.first_kiss:
            update.flags_to_set.append("first_kiss")
            update.event_to_remember = "Первый поцелуй"

        if re.search(r"личн|прошл|семь|детств", message_lower) and not current_state.first_personal_talk:
            update.flags_to_set.append("first_personal_talk")
            update.event_to_remember = "Первый личный разговор"

        # Определяем изменение настроения
        if update.arousal_delta > 15:
            update.new_mood = Mood.INTIMATE
        elif update.affection_delta > 5:
            update.new_mood = Mood.WARM
        elif update.trust_delta < -5:
            update.new_mood = Mood.ANNOYED
        elif update.trust_delta > 5:
            update.new_mood = Mood.NEUTRAL

        return update

    def apply_update(self, state: CharacterState, update: StateUpdate) -> CharacterState:
        """
        Применяет обновление к состоянию персонажа.

        Args:
            state: Текущее состояние
            update: Обновление для применения

        Returns:
            Обновлённое состояние
        """
        # Применяем дельты с ограничениями 0-100
        state.trust = max(0, min(100, state.trust + update.trust_delta))
        state.affection = max(0, min(100, state.affection + update.affection_delta))
        state.arousal = max(0, min(100, state.arousal + update.arousal_delta))
        state.comfort = max(0, min(100, state.comfort + update.comfort_delta))

        # Обновляем настроение
        if update.new_mood:
            state.mood = update.new_mood

        # Устанавливаем флаги
        for flag in update.flags_to_set:
            setattr(state, flag, True)

        # Добавляем событие в память
        if update.event_to_remember:
            state.memorable_events.append(update.event_to_remember)

        # Естественное затухание arousal (если нет стимуляции)
        if update.arousal_delta == 0 and state.arousal > 0:
            state.arousal = max(0, state.arousal - 5)

        # Постепенный рост comfort при позитивных взаимодействиях
        if update.trust_delta > 0 or update.affection_delta > 0:
            state.comfort = min(100, state.comfort + 1)

        return state
