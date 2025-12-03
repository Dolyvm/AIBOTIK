"""Библиотека стандартных условий для roleplay бота."""

from .core import InjectionContext, ConditionEvaluator
from models.state import Mood, RelationshipStage


class StandardConditions:
    """Стандартная библиотека условий для roleplay бота."""

    # === УСЛОВИЯ НА ОСНОВЕ КОЛИЧЕСТВА СООБЩЕНИЙ ===

    @staticmethod
    def first_messages(count: int = 5):
        """Только первые N сообщений."""
        return ConditionEvaluator.message_count_range(0, count)

    @staticmethod
    def after_messages(count: int):
        """После N сообщений."""
        return ConditionEvaluator.message_count_range(count)

    @staticmethod
    def message_range(min_count: int, max_count: int):
        """Диапазон сообщений."""
        return ConditionEvaluator.message_count_range(min_count, max_count)

    # === УСЛОВИЯ НА ОСНОВЕ МЕТРИК СОСТОЯНИЯ ===

    @staticmethod
    def low_trust():
        """Низкое доверие (< 40)."""
        return ConditionEvaluator.state_threshold("trust", 40, "<")

    @staticmethod
    def medium_trust():
        """Среднее доверие (40-70)."""
        def evaluate(ctx: InjectionContext) -> bool:
            return 40 <= ctx.state.trust <= 70
        return evaluate

    @staticmethod
    def high_trust():
        """Высокое доверие (> 70)."""
        return ConditionEvaluator.state_threshold("trust", 70, ">")

    @staticmethod
    def low_affection():
        """Низкая привязанность (< 30)."""
        return ConditionEvaluator.state_threshold("affection", 30, "<")

    @staticmethod
    def high_affection():
        """Высокая привязанность (> 70)."""
        return ConditionEvaluator.state_threshold("affection", 70, ">")

    @staticmethod
    def aroused():
        """Возбуждение > 50."""
        return ConditionEvaluator.state_threshold("arousal", 50, ">")

    @staticmethod
    def highly_aroused():
        """Высокое возбуждение (> 80)."""
        return ConditionEvaluator.state_threshold("arousal", 80, ">")

    # === УСЛОВИЯ НА ОСНОВЕ СТАДИИ ОТНОШЕНИЙ ===

    @staticmethod
    def is_stranger():
        """Стадия: незнакомец."""
        def evaluate(ctx: InjectionContext) -> bool:
            return ctx.state.relationship_stage == RelationshipStage.STRANGER
        return evaluate

    @staticmethod
    def is_friend_or_closer():
        """Стадия: друг или ближе."""
        def evaluate(ctx: InjectionContext) -> bool:
            stages = [RelationshipStage.FRIEND, RelationshipStage.CLOSE_FRIEND, RelationshipStage.INTIMATE]
            return ctx.state.relationship_stage in stages
        return evaluate

    @staticmethod
    def is_intimate():
        """Стадия: интимные отношения."""
        def evaluate(ctx: InjectionContext) -> bool:
            return ctx.state.relationship_stage == RelationshipStage.INTIMATE
        return evaluate

    # === УСЛОВИЯ НА ОСНОВЕ НАСТРОЕНИЯ ===

    @staticmethod
    def mood_is(mood: Mood):
        """Конкретное настроение."""
        def evaluate(ctx: InjectionContext) -> bool:
            return ctx.state.mood == mood
        return evaluate

    # === УСЛОВИЯ НА ОСНОВЕ СОБЫТИЙ ===

    @staticmethod
    def has_summary():
        """Есть summary."""
        return ConditionEvaluator.has_summary()

    @staticmethod
    def no_summary():
        """Нет summary."""
        def evaluate(ctx: InjectionContext) -> bool:
            return ctx.session.summary is None
        return evaluate

    @staticmethod
    def first_touch_happened():
        """Было первое прикосновение."""
        def evaluate(ctx: InjectionContext) -> bool:
            return ctx.state.first_touch
        return evaluate

    # === КОМБИНИРОВАННЫЕ УСЛОВИЯ ===

    @staticmethod
    def early_relationship():
        """Раннее знакомство: первые 10 сообщений ИЛИ низкое доверие."""
        return ConditionEvaluator.any_of(
            StandardConditions.first_messages(10),
            StandardConditions.low_trust()
        )

    @staticmethod
    def intimate_context():
        """Интимный контекст: высокое возбуждение И (высокая привязанность ИЛИ интимная стадия)."""
        return ConditionEvaluator.all_of(
            StandardConditions.aroused(),
            ConditionEvaluator.any_of(
                StandardConditions.high_affection(),
                StandardConditions.is_intimate()
            )
        )
