"""Конкретные типы компонентов промпта."""

from .core import PromptComponent, ComponentPriority, ComponentType, InjectionContext
from typing import Optional, List, Callable, Dict
from datetime import timedelta


class StaticTextComponent(PromptComponent):
    """Компонент со статичным текстом."""

    def __init__(
        self,
        name: str,
        content: str,
        priority: ComponentPriority,
        conditions: List = None,
        estimated_tokens: Optional[int] = None,
        requires: List[str] = None,
        excludes: List[str] = None
    ):
        super().__init__(
            name=name,
            priority=priority,
            component_type=ComponentType.STATIC,
            conditions=conditions or [],
            cache_enabled=True,
            cache_ttl=None,  # Бесконечный кеш
            estimated_tokens=estimated_tokens or len(content) // 4,  # Примерная оценка
            requires=requires or [],
            excludes=excludes or []
        )
        self.content = content

    def render(self, ctx: InjectionContext) -> str:
        return self.content


class TemplateComponent(PromptComponent):
    """Компонент с шаблоном для подстановки."""

    def __init__(
        self,
        name: str,
        template: str,
        priority: ComponentPriority,
        component_type: ComponentType,
        conditions: List = None,
        cache_enabled: bool = True,
        cache_ttl: Optional[timedelta] = None,
        estimated_tokens: Optional[int] = None,
        requires: List[str] = None,
        excludes: List[str] = None
    ):
        super().__init__(
            name=name,
            priority=priority,
            component_type=component_type,
            conditions=conditions or [],
            cache_enabled=cache_enabled,
            cache_ttl=cache_ttl,
            estimated_tokens=estimated_tokens or len(template) // 4,
            requires=requires or [],
            excludes=excludes or []
        )
        self.template = template

    def render(self, ctx: InjectionContext) -> str:
        # Замена плейсхолдеров
        replacements = {
            "{{char}}": ctx.character.name,
            "{{user}}": ctx.user_name,
            "<BOT>": ctx.character.name,
            "<USER>": ctx.user_name,
        }

        content = self.template.format(
            char_name=ctx.character.name,
            user_name=ctx.user_name,
            description=ctx.character.description or "",
            personality=ctx.character.personality or "",
            scenario=self._replace_placeholders(ctx.character.scenario or "", replacements),
            example_dialogue=self._replace_placeholders(
                ctx.character.example_dialogue or "",
                replacements
            )
        )
        return content

    def _replace_placeholders(self, text: str, replacements: Dict[str, str]) -> str:
        """Заменяет плейсхолдеры в тексте."""
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        return text


class DynamicComponent(PromptComponent):
    """Компонент с динамической генерацией."""

    def __init__(
        self,
        name: str,
        generator: Callable[[InjectionContext], str],
        priority: ComponentPriority,
        conditions: List = None,
        estimated_tokens: int = 100,
        requires: List[str] = None,
        excludes: List[str] = None
    ):
        super().__init__(
            name=name,
            priority=priority,
            component_type=ComponentType.DYNAMIC,
            conditions=conditions or [],
            cache_enabled=False,  # Динамические компоненты не кешируются
            estimated_tokens=estimated_tokens,
            requires=requires or [],
            excludes=excludes or []
        )
        self.generator = generator

    def render(self, ctx: InjectionContext) -> str:
        return self.generator(ctx)


class ConditionalComponent(PromptComponent):
    """Компонент с условным контентом."""

    def __init__(
        self,
        name: str,
        condition_map: Dict[Callable[[InjectionContext], bool], str],
        priority: ComponentPriority,
        conditions: List = None,
        default_content: str = "",
        estimated_tokens: int = 200,
        requires: List[str] = None,
        excludes: List[str] = None
    ):
        super().__init__(
            name=name,
            priority=priority,
            component_type=ComponentType.CONTEXTUAL,
            conditions=conditions or [],
            cache_enabled=False,
            estimated_tokens=estimated_tokens,
            requires=requires or [],
            excludes=excludes or []
        )
        self.condition_map = condition_map
        self.default_content = default_content

    def render(self, ctx: InjectionContext) -> str:
        for condition, content in self.condition_map.items():
            if condition(ctx):
                return content
        return self.default_content
