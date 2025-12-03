"""
Dynamic Injection система для промптов.

Архитектурный паттерн для условной загрузки компонентов промпта
на основе контекста, приоритетов и бюджета токенов.
"""

from .core import (
    ComponentPriority,
    ComponentType,
    InjectionContext,
    ConditionEvaluator,
    PromptComponent
)
from .components import (
    StaticTextComponent,
    TemplateComponent,
    DynamicComponent,
    ConditionalComponent
)
from .composer import PromptComposer
from .conditions import StandardConditions

__all__ = [
    "ComponentPriority",
    "ComponentType",
    "InjectionContext",
    "ConditionEvaluator",
    "PromptComponent",
    "StaticTextComponent",
    "TemplateComponent",
    "DynamicComponent",
    "ConditionalComponent",
    "PromptComposer",
    "StandardConditions",
]
