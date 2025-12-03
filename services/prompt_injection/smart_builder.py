"""Умный построитель промптов с Dynamic Injection и автоматическим кешированием."""

from typing import Optional
import logging

from models.character import CharacterData
from models.state import CharacterState
from models.session import UserSession
from .core import InjectionContext
from .composer import PromptComposer
from .cache_manager import CacheInvalidationManager, CacheEvent, detect_state_change_event
from .presets.roleplay import create_roleplay_composer

logger = logging.getLogger(__name__)


class SmartPromptBuilder:
    """
    Высокоуровневый интерфейс для построения промптов с Dynamic Injection.

    Автоматически управляет кешированием, инвалидацией и композицией промптов.
    """

    def __init__(self, token_budget: int = 4000):
        """
        Args:
            token_budget: Максимальный бюджет токенов для промпта
        """
        self.token_budget = token_budget

        # Создаём composer с roleplay preset
        self.composer = create_roleplay_composer(token_budget)

        # Создаём cache manager
        self.cache_manager = CacheInvalidationManager(self.composer)

        # Храним предыдущее состояние для детекции изменений
        self._previous_state: Optional[dict] = None
        self._previous_character_id: Optional[str] = None

        logger.info(
            f"SmartPromptBuilder initialized with {len(self.composer.components)} components, "
            f"token_budget={token_budget}"
        )

    def build_system_prompt(
        self,
        character: CharacterData,
        state: CharacterState,
        session: UserSession,
        user_name: str,
        message_count: int
    ) -> str:
        """
        Строит системный промпт с автоматическим управлением кешем.

        Args:
            character: Данные персонажа
            state: Текущее состояние персонажа
            session: Сессия пользователя
            user_name: Имя пользователя
            message_count: Количество сообщений в текущей сессии

        Returns:
            Скомпонованный системный промпт
        """
        # === АВТОМАТИЧЕСКАЯ ИНВАЛИДАЦИЯ КЕША ===

        # 1. Проверяем смену персонажа
        current_char_id = character.name  # Используем имя как ID
        if self._previous_character_id != current_char_id:
            logger.info(f"🔄 Character switched: {self._previous_character_id} → {current_char_id}")
            self.cache_manager.handle_event(CacheEvent.CHARACTER_SWITCHED)
            self._previous_character_id = current_char_id

        # 2. Проверяем изменение состояния
        current_state = {
            "trust": state.trust,
            "affection": state.affection,
            "arousal": state.arousal,
            "mood": state.mood,
            "relationship_stage": state.relationship_stage,
        }

        if self._previous_state is not None:
            # Детектируем тип изменения
            if current_state["mood"] != self._previous_state["mood"]:
                self.cache_manager.handle_event(CacheEvent.MOOD_CHANGED)

            if current_state["relationship_stage"] != self._previous_state["relationship_stage"]:
                self.cache_manager.handle_event(CacheEvent.RELATIONSHIP_STAGE_CHANGED)

            # Проверяем изменение метрик
            event = detect_state_change_event(self._previous_state, current_state)
            self.cache_manager.handle_event(event)

        self._previous_state = current_state.copy()

        # 3. Проверяем создание summary
        # (Детекция должна происходить в handlers/messages.py)

        # === КОМПОЗИЦИЯ ПРОМПТА ===

        # Создаём контекст для композиции
        ctx = InjectionContext(
            session=session,
            state=state,
            character=character,
            message_count=message_count,
            user_name=user_name,
            token_budget=self.token_budget,
            used_tokens=0
        )

        # Компонуем промпт
        prompt = self.composer.compose(ctx)

        # Логируем статистику
        logger.info(
            f"📋 Prompt built: ~{ctx.used_tokens}/{self.token_budget} tokens "
            f"({ctx.used_tokens/self.token_budget*100:.1f}% of budget)"
        )

        return prompt

    def notify_summary_created(self):
        """Уведомляет builder о создании нового summary."""
        logger.info("📝 Summary created notification")
        self.cache_manager.handle_event(CacheEvent.SUMMARY_CREATED)

    def notify_character_updated(self):
        """Уведомляет builder об обновлении данных персонажа."""
        logger.info("🔄 Character data updated notification")
        self.cache_manager.handle_event(CacheEvent.CHARACTER_UPDATED)

    def notify_first_touch(self):
        """Уведомляет builder о первом прикосновении."""
        logger.info("🤝 First touch notification")
        self.cache_manager.handle_event(CacheEvent.FIRST_TOUCH)

    def reset_for_new_session(self):
        """Сбрасывает состояние для новой сессии."""
        logger.info("🔄 Resetting for new session")
        self.cache_manager.handle_event(CacheEvent.NEW_SESSION)
        self._previous_state = None
        self._previous_character_id = None

    def invalidate_all(self):
        """Инвалидирует все кеши (для ручного сброса)."""
        logger.info("🔄 Manual cache invalidation")
        self.cache_manager.invalidate_all()

    def get_component_stats(self) -> dict:
        """
        Возвращает статистику по компонентам.

        Returns:
            Dict с информацией о компонентах и их кешировании
        """
        stats = {
            "total_components": len(self.composer.components),
            "token_budget": self.token_budget,
            "components": []
        }

        for component in self.composer.components:
            cache_status = "no cache"
            if component.cache_enabled:
                if component._cached_content is not None:
                    cache_status = "cached"
                else:
                    cache_status = "cache miss"

            stats["components"].append({
                "name": component.name,
                "priority": component.priority.name,
                "type": component.component_type.name,
                "estimated_tokens": component.estimated_tokens,
                "cache_status": cache_status,
                "cache_enabled": component.cache_enabled,
                "conditions_count": len(component.conditions),
            })

        return stats

    def log_component_stats(self):
        """Логирует статистику по компонентам."""
        stats = self.get_component_stats()

        logger.info(f"\n{'='*80}")
        logger.info(f"COMPONENT STATISTICS")
        logger.info(f"{'='*80}")
        logger.info(f"Total components: {stats['total_components']}")
        logger.info(f"Token budget: {stats['token_budget']}")
        logger.info(f"\nComponents:")

        for comp in stats["components"]:
            logger.info(
                f"  • {comp['name']}: "
                f"{comp['priority']} / {comp['type']} / "
                f"~{comp['estimated_tokens']}t / "
                f"{comp['cache_status']} / "
                f"{comp['conditions_count']} conditions"
            )

        logger.info(f"{'='*80}\n")
