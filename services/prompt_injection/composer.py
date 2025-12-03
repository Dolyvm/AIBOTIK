"""Система композиции промптов из компонентов."""

from typing import List, Dict, Optional
from .core import PromptComponent, InjectionContext, ComponentPriority
import logging

logger = logging.getLogger(__name__)


class PromptComposer:
    """Компонует финальный промпт из компонентов."""

    def __init__(self, token_budget: int = 4000):
        self.token_budget = token_budget
        self.components: List[PromptComponent] = []
        self._component_map: Dict[str, PromptComponent] = {}

    def register(self, component: PromptComponent):
        """Регистрирует компонент."""
        self.components.append(component)
        self._component_map[component.name] = component
        logger.debug(
            f"Registered component: {component.name} "
            f"(priority={component.priority.value}, type={component.component_type.value})"
        )

    def compose(self, ctx: InjectionContext) -> str:
        """Компонует финальный промпт."""
        ctx.token_budget = self.token_budget
        ctx.used_tokens = 0

        # 1. Фильтруем компоненты по условиям
        eligible_components = [
            comp for comp in self.components
            if comp.should_inject(ctx)
        ]

        logger.info(
            f"Eligible components: {len(eligible_components)}/{len(self.components)}"
        )

        # 2. Проверяем зависимости
        eligible_components = self._resolve_dependencies(eligible_components)

        # 3. Сортируем по приоритету (высокий приоритет = большее число)
        eligible_components.sort(key=lambda c: c.priority.value, reverse=True)

        # 4. Собираем промпт с учетом бюджета
        sections = []
        total_tokens = 0

        for component in eligible_components:
            # Проверяем бюджет
            if total_tokens + component.estimated_tokens > self.token_budget:
                if component.priority == ComponentPriority.CRITICAL:
                    logger.warning(
                        f"Component {component.name} exceeds budget but is CRITICAL, including anyway"
                    )
                else:
                    logger.info(
                        f"Component {component.name} skipped due to token budget "
                        f"({total_tokens + component.estimated_tokens} > {self.token_budget})"
                    )
                    continue

            # Генерируем содержимое
            try:
                ctx.used_tokens = total_tokens
                content = component.get_content(ctx)

                if content.strip():
                    sections.append(content)
                    actual_tokens = len(content) // 4  # Примерная оценка
                    total_tokens += actual_tokens

                    cache_status = "from cache" if (
                        component.cache_enabled and
                        component._cached_content is not None and
                        component._is_cache_valid()
                    ) else "generated"

                    logger.debug(
                        f"✓ {component.name}: {actual_tokens} tokens ({cache_status}) "
                        f"(total: {total_tokens}/{self.token_budget})"
                    )

            except Exception as e:
                logger.error(f"Error rendering component {component.name}: {e}", exc_info=True)

        # 5. Объединяем секции
        final_prompt = "\n\n".join(sections)

        logger.info(
            f"Composed prompt: {len(sections)} sections, "
            f"~{total_tokens} tokens ({total_tokens/self.token_budget*100:.1f}% of budget)"
        )

        return final_prompt

    def _resolve_dependencies(
        self,
        components: List[PromptComponent]
    ) -> List[PromptComponent]:
        """Разрешает зависимости между компонентами."""
        component_names = {c.name for c in components}
        resolved = []

        for component in components:
            # Проверяем requires
            if component.requires:
                missing = set(component.requires) - component_names
                if missing:
                    logger.warning(
                        f"Component {component.name} requires {missing} but they are not available, skipping"
                    )
                    continue

            # Проверяем excludes
            if component.excludes:
                conflicting = set(component.excludes) & component_names
                if conflicting:
                    logger.warning(
                        f"Component {component.name} conflicts with {conflicting}, skipping"
                    )
                    continue

            resolved.append(component)

        return resolved

    def get_component(self, name: str) -> Optional[PromptComponent]:
        """Получает компонент по имени."""
        return self._component_map.get(name)

    def invalidate_cache(self, component_name: Optional[str] = None):
        """Инвалидирует кеш компонента(ов)."""
        if component_name:
            if component_name in self._component_map:
                self._component_map[component_name].invalidate_cache()
                logger.debug(f"Invalidated cache for component: {component_name}")
        else:
            for component in self.components:
                component.invalidate_cache()
            logger.debug("Invalidated all component caches")
