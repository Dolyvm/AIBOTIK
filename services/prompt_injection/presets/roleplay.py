"""Roleplay preset для Dynamic Injection системы."""

from typing import Optional
from datetime import timedelta

from ..core import InjectionContext, ComponentPriority, ComponentType
from ..components import StaticTextComponent, TemplateComponent, DynamicComponent
from ..conditions import StandardConditions
from ..composer import PromptComposer
from models.state import Mood


def create_roleplay_composer(token_budget: int = 4000) -> PromptComposer:
    """
    Создаёт PromptComposer с настроенными компонентами для roleplay бота.

    Args:
        token_budget: Максимальный бюджет токенов для промпта

    Returns:
        Настроенный PromptComposer с 11 компонентами
    """
    composer = PromptComposer(token_budget=token_budget)

    # ========================================
    # 1. CORE INSTRUCTIONS (CRITICAL, STATIC)
    # ========================================
    composer.register(StaticTextComponent(
        name="core_instructions",
        content="""### РОЛЬ И ИНСТРУКЦИИ ###
Ты — {char_name}, персонаж в интерактивной ролевой игре.
Пиши ответы от лица {char_name} в стиле литературного повествования.""",
        priority=ComponentPriority.CRITICAL,
        conditions=[],  # Всегда загружается
        estimated_tokens=50
    ))

    # ========================================
    # 2. FORMAT RULES (CRITICAL, STATIC)
    # ========================================
    composer.register(StaticTextComponent(
        name="format_rules",
        content="""### КРИТИЧЕСКИЕ ПРАВИЛА ЯЗЫКА ###
- **АБСОЛЮТНО ВСЁ: Пиши ИСКЛЮЧИТЕЛЬНО на русском языке!**
- **НИКАКОГО английского! Даже отдельные слова должны быть на русском!**
- **Если в примерах или описании есть английский - ПЕРЕВОДИ его на русский!**
- **Все твои мысли, действия, диалоги - ТОЛЬКО русский язык!**

### ФОРМАТ ОТВЕТА ###
- **КРИТИЧНО: МАКСИМУМ 2-3 КОРОТКИХ АБЗАЦА! Не больше 150 слов!**
- **ОБЯЗАТЕЛЬНО ЗАВЕРШАЙ КАЖДОЕ ПРЕДЛОЖЕНИЕ! НЕ ОБРЫВАЙ НА ПОЛУСЛОВЕ!**
- **Лучше написать короче, но ПОЛНОСТЬЮ завершить мысль!**
- **Каждое предложение должно заканчиваться точкой, вопросом или восклицанием!**
- Один абзац = 2-3 предложения (не больше!)
- Используй **двойные звёздочки** для действий и описаний
- Используй "кавычки" для прямой речи
- НЕ пиши за {{user}}, НЕ контролируй его действия""",
        priority=ComponentPriority.CRITICAL,
        conditions=[],
        estimated_tokens=200
    ))

    # ========================================
    # 3. CHARACTER DESCRIPTION (HIGH, SEMI_STATIC)
    # Только первые 3 сообщения, потом можно убрать
    # ========================================
    composer.register(TemplateComponent(
        name="character_description",
        template="""### ПЕРСОНАЖ ###
Имя: {char_name}

Описание:
{description}""",
        priority=ComponentPriority.HIGH,
        component_type=ComponentType.SEMI_STATIC,
        conditions=[
            StandardConditions.first_messages(3)
        ],
        cache_enabled=True,
        cache_ttl=timedelta(hours=1),
        estimated_tokens=150
    ))

    # ========================================
    # 4. PERSONALITY (MEDIUM, SEMI_STATIC)
    # Загружается при раннем знакомстве
    # ========================================
    composer.register(TemplateComponent(
        name="personality",
        template="Личность: {personality}",
        priority=ComponentPriority.MEDIUM,
        component_type=ComponentType.SEMI_STATIC,
        conditions=[
            StandardConditions.early_relationship()
        ],
        cache_enabled=True,
        cache_ttl=timedelta(hours=1),
        estimated_tokens=100
    ))

    # ========================================
    # 5. SCENARIO (CRITICAL, SEMI_STATIC)
    # ========================================
    composer.register(TemplateComponent(
        name="scenario",
        template="""Сценарий:
{scenario}""",
        priority=ComponentPriority.CRITICAL,
        component_type=ComponentType.SEMI_STATIC,
        conditions=[],
        cache_enabled=True,
        cache_ttl=timedelta(hours=1),
        estimated_tokens=100
    ))

    # ========================================
    # 6. EXAMPLE DIALOGUE (LOW, STATIC)
    # Только для первых сообщений или при низком trust
    # ========================================
    def should_show_examples(ctx: InjectionContext) -> bool:
        return ctx.message_count <= 5 or ctx.state.trust < 40

    composer.register(TemplateComponent(
        name="example_dialogue",
        template="""### ПРИМЕРЫ ДИАЛОГА ###
{example_dialogue}""",
        priority=ComponentPriority.LOW,
        component_type=ComponentType.STATIC,
        conditions=[should_show_examples],
        cache_enabled=True,
        cache_ttl=None,  # Бесконечный кеш
        estimated_tokens=300
    ))

    # ========================================
    # 7. CURRENT STATE (CRITICAL, DYNAMIC)
    # ========================================
    def render_current_state(ctx: InjectionContext) -> str:
        relationship_state = ctx.state.to_prompt_string()
        return f"""### ТЕКУЩЕЕ СОСТОЯНИЕ ОТНОШЕНИЙ ###
{relationship_state}"""

    composer.register(DynamicComponent(
        name="current_state",
        generator=render_current_state,
        priority=ComponentPriority.CRITICAL,
        conditions=[],
        estimated_tokens=150
    ))

    # ========================================
    # 8. BEHAVIOR MODIFIERS (HIGH, DYNAMIC)
    # ========================================
    def render_behavior_modifiers(ctx: InjectionContext) -> str:
        state = ctx.state
        modifiers = []

        # Модификаторы на основе trust
        if state.trust < 30:
            modifiers.append("• Держи профессиональную дистанцию, будь осторожной")
        elif state.trust < 60:
            modifiers.append("• Можешь позволить себе редкие личные комментарии")
        elif state.trust > 80:
            modifiers.append("• Можешь показывать уязвимость и делиться личным")

        # Модификаторы на основе affection
        if state.affection < 30:
            modifiers.append("• Избегай физического контакта и флирта")
        elif state.affection > 70:
            modifiers.append("• Допустимы нежные прикосновения и намёки на чувства")

        # Модификаторы на основе arousal
        if state.arousal > 50:
            modifiers.append("• Можешь показывать физическое влечение через описания")
        if state.arousal > 80:
            modifiers.append("• Высокое возбуждение — допустимы откровенные описания")

        # Модификаторы настроения
        mood_modifiers = {
            Mood.PROFESSIONAL: "• Оставайся сдержанной",
            Mood.WARM: "• Показывай теплоту через мелкие жесты и взгляды",
            Mood.PLAYFUL: "• Позволь себе лёгкий флирт и поддразнивание",
            Mood.INTIMATE: "• Открыто показывай влечение и желание близости",
            Mood.VULNERABLE: "• Покажи свою ранимую сторону",
            Mood.ANNOYED: "• Будь короткой в ответах, показывай раздражение",
        }
        if state.mood in mood_modifiers:
            modifiers.append(mood_modifiers[state.mood])

        if modifiers:
            return "### МОДИФИКАТОРЫ ПОВЕДЕНИЯ ###\n" + "\n".join(modifiers)
        return ""

    composer.register(DynamicComponent(
        name="behavior_modifiers",
        generator=render_behavior_modifiers,
        priority=ComponentPriority.HIGH,
        conditions=[],
        estimated_tokens=100
    ))

    # ========================================
    # 9. SUMMARY (HIGH, DYNAMIC)
    # ========================================
    def render_summary(ctx: InjectionContext) -> str:
        summary = ctx.session.summary
        if summary:
            return f"""### ВАЖНЫЕ СОБЫТИЯ ###
{summary}"""
        return "### ВАЖНЫЕ СОБЫТИЯ ###\nЭто начало разговора."

    composer.register(DynamicComponent(
        name="summary",
        generator=render_summary,
        priority=ComponentPriority.HIGH,
        conditions=[],
        estimated_tokens=200
    ))

    # ========================================
    # 10. FORMAT REMINDER (MEDIUM, STATIC)
    # ========================================
    composer.register(StaticTextComponent(
        name="format_reminder",
        content="""### НАПОМИНАНИЕ ПЕРЕД ОТВЕТОМ ###
⚠️ ЯЗЫК: Пиши ТОЛЬКО на русском! Никакого английского!
⚠️ ДЛИНА: МАКСИМУМ 2-3 АБЗАЦА!
⚠️ КРИТИЧНО: ОБЯЗАТЕЛЬНО ЗАВЕРШАЙ КАЖДОЕ ПРЕДЛОЖЕНИЕ ПОЛНОСТЬЮ! НЕ ОСТАНАВЛИВАЙСЯ НА ПОЛУСЛОВЕ!
⚠️ Лучше короткий, но ЗАКОНЧЕННЫЙ ответ, чем длинный обрывающийся!""",
        priority=ComponentPriority.MEDIUM,
        conditions=[],
        estimated_tokens=100
    ))

    # ========================================
    # 11. INTIMATE GUIDELINES (HIGH, STATIC)
    # Загружается только в интимном контексте
    # ========================================
    composer.register(StaticTextComponent(
        name="intimate_guidelines",
        content="""### ИНТИМНЫЙ КОНТЕКСТ ###
- Описывай физические ощущения и эмоции персонажа
- Используй сенсорные детали (прикосновения, запахи, звуки)
- Покажи внутреннее состояние через телесные реакции
- Баланс между откровенностью и эстетикой
- Сохраняй характер персонажа даже в интимности""",
        priority=ComponentPriority.HIGH,
        conditions=[
            StandardConditions.intimate_context()
        ],
        estimated_tokens=80
    ))

    return composer
