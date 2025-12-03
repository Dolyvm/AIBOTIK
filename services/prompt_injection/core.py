"""Базовые классы для Dynamic Injection архитектуры."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Callable, Optional, Any, List
from enum import Enum
import hashlib
from datetime import datetime, timedelta


class ComponentPriority(Enum):
    """Приоритет компонента в промпте."""
    CRITICAL = 1000    # Всегда загружается (Core Instructions, Scenario, State)
    HIGH = 500         # Почти всегда (Modifiers, Summary)
    MEDIUM = 100       # Условно (Personality)
    LOW = 10           # Опционально (Examples)
    OPTIONAL = 1       # Только при большом бюджете


class ComponentType(Enum):
    """Тип компонента по характеру данных."""
    STATIC = "static"              # Никогда не меняется (примеры диалога)
    SEMI_STATIC = "semi_static"    # Меняется редко (personality, description)
    DYNAMIC = "dynamic"            # Меняется часто (state, modifiers)
    CONTEXTUAL = "contextual"      # Зависит от контекста (summary, recent events)


@dataclass
class InjectionContext:
    """Контекст для принятия решений об инъекции."""
    session: Any  # UserSession
    state: Any    # CharacterState
    character: Any  # CharacterData
    message_count: int
    user_name: str
    token_budget: int = 4000  # Максимум токенов для промпта
    used_tokens: int = 0


class ConditionEvaluator:
    """Оценивает условия для загрузки компонентов."""

    @staticmethod
    def message_count_range(min_count: int, max_count: Optional[int] = None):
        """Условие: диапазон количества сообщений."""
        def evaluate(ctx: InjectionContext) -> bool:
            if max_count is None:
                return ctx.message_count >= min_count
            return min_count <= ctx.message_count <= max_count
        return evaluate

    @staticmethod
    def state_threshold(metric: str, threshold: int, operator: str = ">="):
        """Условие: порог метрики состояния."""
        def evaluate(ctx: InjectionContext) -> bool:
            value = getattr(ctx.state, metric)
            if operator == ">=":
                return value >= threshold
            elif operator == "<=":
                return value <= threshold
            elif operator == ">":
                return value > threshold
            elif operator == "<":
                return value < threshold
            return False
        return evaluate

    @staticmethod
    def has_summary():
        """Условие: есть ли summary."""
        def evaluate(ctx: InjectionContext) -> bool:
            return ctx.session.summary is not None
        return evaluate

    @staticmethod
    def any_of(*conditions):
        """ИЛИ: хотя бы одно условие."""
        def evaluate(ctx: InjectionContext) -> bool:
            return any(cond(ctx) for cond in conditions)
        return evaluate

    @staticmethod
    def all_of(*conditions):
        """И: все условия."""
        def evaluate(ctx: InjectionContext) -> bool:
            return all(cond(ctx) for cond in conditions)
        return evaluate


@dataclass
class PromptComponent(ABC):
    """Базовый класс для компонента промпта."""

    # Основные параметры
    name: str
    priority: ComponentPriority
    component_type: ComponentType

    # Условия инъекции
    conditions: List[Callable[[InjectionContext], bool]] = field(default_factory=list)

    # Кеширование
    cache_enabled: bool = True
    cache_key: Optional[str] = None
    cache_ttl: Optional[timedelta] = None  # None = бесконечно

    # Оценка размера
    estimated_tokens: int = 0

    # Зависимости
    requires: List[str] = field(default_factory=list)  # Имена компонентов, которые должны быть
    excludes: List[str] = field(default_factory=list)  # Имена компонентов, с которыми несовместим

    # Кеш-данные (внутреннее)
    _cached_content: Optional[str] = field(default=None, init=False, repr=False)
    _cached_at: Optional[datetime] = field(default=None, init=False, repr=False)
    _cached_hash: Optional[str] = field(default=None, init=False, repr=False)

    @abstractmethod
    def render(self, ctx: InjectionContext) -> str:
        """Генерирует содержимое компонента."""
        pass

    def should_inject(self, ctx: InjectionContext) -> bool:
        """Проверяет, должен ли компонент быть загружен."""
        # Проверяем все условия
        if not all(condition(ctx) for condition in self.conditions):
            return False

        # Проверяем бюджет токенов
        if ctx.used_tokens + self.estimated_tokens > ctx.token_budget:
            # Только CRITICAL компоненты могут превысить бюджет
            if self.priority != ComponentPriority.CRITICAL:
                return False

        return True

    def get_content(self, ctx: InjectionContext) -> str:
        """Получает содержимое с учетом кеша."""
        if not self.cache_enabled:
            return self.render(ctx)

        # Проверяем валидность кеша
        if self._is_cache_valid():
            return self._cached_content

        # Генерируем новое содержимое
        content = self.render(ctx)

        # Сохраняем в кеш
        self._cached_content = content
        self._cached_at = datetime.now()
        self._cached_hash = self._compute_cache_hash(ctx)

        return content

    def _is_cache_valid(self) -> bool:
        """Проверяет валидность кеша."""
        if self._cached_content is None:
            return False

        # Проверяем TTL
        if self.cache_ttl is not None:
            if datetime.now() - self._cached_at > self.cache_ttl:
                return False

        return True

    def _compute_cache_hash(self, ctx: InjectionContext) -> str:
        """Вычисляет хеш для кеша."""
        if self.cache_key:
            # Используем явный cache_key
            return self.cache_key.format(
                char_id=ctx.character.name,
                user_id=ctx.session.user_id
            )
        # Используем хеш контекста
        return hashlib.md5(
            f"{self.name}:{ctx.character.name}:{ctx.session.user_id}".encode()
        ).hexdigest()

    def invalidate_cache(self):
        """Инвалидирует кеш."""
        self._cached_content = None
        self._cached_at = None
        self._cached_hash = None
