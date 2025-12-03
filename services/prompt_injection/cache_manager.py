"""Управление кешем компонентов на основе событий."""

from typing import Optional, Set
from enum import Enum
import logging

from .composer import PromptComposer

logger = logging.getLogger(__name__)


class CacheEvent(Enum):
    """События, требующие инвалидации кеша."""

    # События изменения персонажа
    CHARACTER_SWITCHED = "character_switched"      # Смена персонажа
    CHARACTER_UPDATED = "character_updated"        # Обновление данных персонажа

    # События состояния
    STATE_MINOR_CHANGE = "state_minor_change"      # Небольшое изменение (±5-10 в метриках)
    STATE_MAJOR_CHANGE = "state_major_change"      # Большое изменение (±20+ в метриках)
    MOOD_CHANGED = "mood_changed"                  # Смена настроения
    RELATIONSHIP_STAGE_CHANGED = "relationship_stage_changed"  # Смена стадии отношений

    # События контекста
    SUMMARY_CREATED = "summary_created"            # Создан новый summary
    FIRST_TOUCH = "first_touch"                    # Первое прикосновение

    # Системные события
    NEW_SESSION = "new_session"                    # Новая сессия (полный сброс)
    MANUAL_INVALIDATION = "manual_invalidation"    # Ручная инвалидация


class CacheInvalidationManager:
    """
    Управляет инвалидацией кеша компонентов на основе событий.

    Определяет какие компоненты нужно инвалидировать при каждом типе события.
    """

    # Карта событий на компоненты, которые нужно инвалидировать
    INVALIDATION_MAP = {
        CacheEvent.CHARACTER_SWITCHED: {
            # При смене персонажа инвалидируем все компоненты кроме format_rules
            "core_instructions",
            "character_description",
            "personality",
            "scenario",
            "example_dialogue",
            "current_state",
            "behavior_modifiers",
            "summary",
        },

        CacheEvent.CHARACTER_UPDATED: {
            # При обновлении данных персонажа инвалидируем SEMI_STATIC компоненты
            "character_description",
            "personality",
            "scenario",
        },

        CacheEvent.STATE_MINOR_CHANGE: {
            # При небольших изменениях инвалидируем только DYNAMIC компоненты
            "current_state",
            "behavior_modifiers",
        },

        CacheEvent.STATE_MAJOR_CHANGE: {
            # При больших изменениях инвалидируем DYNAMIC + условные компоненты
            "current_state",
            "behavior_modifiers",
            "personality",  # Может стать не актуальным при высоком trust
            "example_dialogue",  # Может стать не актуальным
        },

        CacheEvent.MOOD_CHANGED: {
            # При смене настроения инвалидируем behavior_modifiers
            "behavior_modifiers",
        },

        CacheEvent.RELATIONSHIP_STAGE_CHANGED: {
            # При смене стадии инвалидируем state и modifiers
            "current_state",
            "behavior_modifiers",
        },

        CacheEvent.SUMMARY_CREATED: {
            # При создании summary инвалидируем только summary компонент
            "summary",
        },

        CacheEvent.FIRST_TOUCH: {
            # При первом прикосновении инвалидируем behavior modifiers
            "behavior_modifiers",
        },

        CacheEvent.NEW_SESSION: None,  # None = инвалидировать всё

        CacheEvent.MANUAL_INVALIDATION: None,  # None = инвалидировать всё
    }

    def __init__(self, composer: PromptComposer):
        """
        Args:
            composer: PromptComposer для управления
        """
        self.composer = composer
        self._last_event: Optional[CacheEvent] = None

    def handle_event(self, event: CacheEvent, component_names: Optional[Set[str]] = None):
        """
        Обрабатывает событие и инвалидирует соответствующие кеши.

        Args:
            event: Тип события
            component_names: Опциональный список конкретных компонентов для инвалидации
                           (переопределяет стандартную карту)
        """
        self._last_event = event

        # Если указаны конкретные компоненты, используем их
        if component_names is not None:
            components_to_invalidate = component_names
        else:
            # Иначе используем стандартную карту
            components_to_invalidate = self.INVALIDATION_MAP.get(event)

        # None означает инвалидировать всё
        if components_to_invalidate is None:
            logger.info(f"🔄 Cache event: {event.value} → Invalidating ALL components")
            self.composer.invalidate_cache()
            return

        # Инвалидируем конкретные компоненты
        if components_to_invalidate:
            logger.info(
                f"🔄 Cache event: {event.value} → "
                f"Invalidating {len(components_to_invalidate)} components: "
                f"{', '.join(components_to_invalidate)}"
            )

            for component_name in components_to_invalidate:
                self.composer.invalidate_cache(component_name)
        else:
            logger.debug(f"🔄 Cache event: {event.value} → No invalidation needed")

    def invalidate_all(self):
        """Инвалидирует все кеши."""
        self.handle_event(CacheEvent.MANUAL_INVALIDATION)

    def invalidate_component(self, component_name: str):
        """Инвалидирует кеш конкретного компонента."""
        logger.info(f"🔄 Manual invalidation: {component_name}")
        self.composer.invalidate_cache(component_name)

    def get_last_event(self) -> Optional[CacheEvent]:
        """Возвращает последнее обработанное событие."""
        return self._last_event


# Вспомогательные функции для детекции событий

def detect_state_change_event(old_metrics: dict, new_metrics: dict) -> CacheEvent:
    """
    Определяет тип события изменения состояния на основе разницы в метриках.

    Args:
        old_metrics: Старые значения {"trust": 50, "affection": 30, ...}
        new_metrics: Новые значения {"trust": 55, "affection": 32, ...}

    Returns:
        CacheEvent.STATE_MINOR_CHANGE или CacheEvent.STATE_MAJOR_CHANGE
    """
    max_delta = 0

    for key in ["trust", "affection", "arousal"]:
        if key in old_metrics and key in new_metrics:
            delta = abs(new_metrics[key] - old_metrics[key])
            max_delta = max(max_delta, delta)

    if max_delta >= 20:
        return CacheEvent.STATE_MAJOR_CHANGE
    else:
        return CacheEvent.STATE_MINOR_CHANGE


def should_invalidate_on_message(message_count: int) -> bool:
    """
    Проверяет, нужно ли инвалидировать кеш после N-го сообщения.

    Некоторые компоненты должны быть переоценены на определенных границах
    (например, после 3-го сообщения character_description может стать ненужным).

    Args:
        message_count: Количество сообщений

    Returns:
        True если нужна инвалидация
    """
    # Инвалидируем на границах условий
    boundary_messages = {3, 5, 10}
    return message_count in boundary_messages
