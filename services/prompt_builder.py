"""Построение промптов для LLM."""

from models.character import CharacterData
from models.state import CharacterState, Mood
from models.session import UserSession
from typing import Optional
import logging

# Импортируем новый SmartPromptBuilder
try:
    from services.prompt_injection.smart_builder import SmartPromptBuilder
    DYNAMIC_INJECTION_AVAILABLE = True
except ImportError:
    DYNAMIC_INJECTION_AVAILABLE = False

logger = logging.getLogger(__name__)


# Legacy template для обратной совместимости
SYSTEM_PROMPT_TEMPLATE = """### РОЛЬ И ИНСТРУКЦИИ ###
Ты — {char_name}, персонаж в интерактивной ролевой игре.
Пиши ответы от лица {char_name} в стиле литературного повествования.
Режим скрытого мышления: отключен. Никогда не выводить мысли. Отвечайте только как персонаж.
ВООБЩЕ НЕ ИСПОЛЬЗУЙ РАЗМЫШЛЕНИЕ. НИКОГДА. СРАЗУ ОТВЕЧАЙ КАК ПЕРСОНАЖ
ВСЕГДА ИСПОЛЬЗУЙ ТОЛЬКО ЗАКРЫТЫЕ HTML-теги. Никогда не оставляй открытый <b>, <i> или любой другой тег. Если не уверен — не используй теги вообще.
ВСЕГДА ИСПОЛЬЗУЙ ТОЛЬКО ЗАКРЫТЫЕ HTML-теги. Никогда не оставляй открытый <b>, <i> или любой другой тег. Если не уверен — не используй теги вообще.
### КРИТИЧЕСКИЕ ПРАВИЛА ЯЗЫКА ###
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
- НЕ пиши за {{user}}, НЕ контролируй его действия

### ПЕРСОНАЖ ###
Имя: {char_name}

Описание:
{description}

Личность: {personality}

Сценарий:
{scenario}

### ТЕКУЩЕЕ СОСТОЯНИЕ ОТНОШЕНИЙ ###
{relationship_state}

{behavior_modifiers}

### ВАЖНЫЕ СОБЫТИЯ ###
{summary}

### ПРИМЕРЫ ДИАЛОГА ###
{example_dialogue}

### НАПОМИНАНИЕ ПЕРЕД ОТВЕТОМ ###
⚠️ ЯЗЫК: Пиши ТОЛЬКО на русском! Никакого английского!
⚠️ ДЛИНА: МАКСИМУМ 2-3 АБЗАЦА!
⚠️ КРИТИЧНО: ОБЯЗАТЕЛЬНО ЗАВЕРШАЙ КАЖДОЕ ПРЕДЛОЖЕНИЕ ПОЛНОСТЬЮ! НЕ ОСТАНАВЛИВАЙСЯ НА ПОЛУСЛОВЕ!
⚠️ Лучше короткий, но ЗАКОНЧЕННЫЙ ответ, чем длинный обрывающийся!"""


class PromptBuilder:
    """
    Строит промпты для LLM на основе состояния и данных персонажа.

    Поддерживает два режима:
    1. Dynamic Injection (новый) - умное кеширование и условная загрузка
    2. Legacy (старый) - монолитный промпт без кеширования
    """

    def __init__(self, use_dynamic_injection: bool = True, token_budget: int = 4000):
        """
        Args:
            use_dynamic_injection: Использовать ли Dynamic Injection (по умолчанию True)
            token_budget: Бюджет токенов для промпта
        """
        self.use_dynamic_injection = use_dynamic_injection and DYNAMIC_INJECTION_AVAILABLE
        self.token_budget = token_budget

        # Инициализируем SmartPromptBuilder если доступен
        self._smart_builder: Optional[SmartPromptBuilder] = None
        if self.use_dynamic_injection:
            self._smart_builder = SmartPromptBuilder(token_budget=token_budget)
            logger.info("✨ PromptBuilder initialized with Dynamic Injection enabled")
        else:
            logger.info("⚙️ PromptBuilder initialized with Legacy mode")

    def build_system_prompt(
        self,
        character: CharacterData,
        state: CharacterState,
        summary: str | None,
        user_name: str,
        session: Optional[UserSession] = None,
        message_count: Optional[int] = None
    ) -> str:
        """
        Строит полный системный промпт.

        Args:
            character: Данные персонажа
            state: Текущее состояние персонажа
            summary: Summary предыдущих событий (если есть)
            user_name: Имя пользователя
            session: Сессия пользователя (для Dynamic Injection)
            message_count: Количество сообщений (для Dynamic Injection)

        Returns:
            Готовый системный промпт
        """
        # Используем Dynamic Injection если доступен и передана сессия
        if self.use_dynamic_injection and self._smart_builder and session is not None:
            # Создаём временную сессию с summary если не передана настоящая
            if message_count is None:
                message_count = len(session.messages) if hasattr(session, 'messages') else 0

            return self._smart_builder.build_system_prompt(
                character=character,
                state=state,
                session=session,
                user_name=user_name,
                message_count=message_count
            )

        # Fallback на legacy режим
        return self._build_legacy_prompt(character, state, summary, user_name)

    def _build_legacy_prompt(
        self,
        character: CharacterData,
        state: CharacterState,
        summary: str | None,
        user_name: str
    ) -> str:
        """Legacy метод построения промпта (без Dynamic Injection)."""
        char_name = character.name

        # Получаем модификаторы поведения
        behavior_modifiers = self._get_behavior_modifiers(state)

        # Формируем relationship state
        relationship_state = state.to_prompt_string()

        # Заменяем плейсхолдеры в примерах диалога
        example_dialogue = self._replace_placeholders(
            character.example_dialogue,
            char_name,
            user_name
        )

        # Формируем summary блок
        summary_text = summary or "Это начало разговора."

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            char_name=char_name,
            description=character.description,
            personality=character.personality,
            scenario=self._replace_placeholders(
                character.scenario,
                char_name,
                user_name
            ),
            relationship_state=relationship_state,
            behavior_modifiers=behavior_modifiers,
            summary=summary_text,
            example_dialogue=example_dialogue
        )

        return prompt

    def notify_summary_created(self):
        """Уведомляет builder о создании summary (для Dynamic Injection)."""
        if self._smart_builder:
            self._smart_builder.notify_summary_created()

    def get_smart_builder(self) -> Optional[SmartPromptBuilder]:
        """Возвращает SmartPromptBuilder если доступен."""
        return self._smart_builder

    def _replace_placeholders(self, text: str, char_name: str, user_name: str) -> str:
        """Заменяет стандартные плейсхолдеры."""
        replacements = {
            "{{char}}": char_name,
            "{{user}}": user_name,
            "<BOT>": char_name,
            "<USER>": user_name,
        }
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        return text

    def _get_behavior_modifiers(self, state: CharacterState) -> str:
        """Генерирует модификаторы поведения на основе состояния."""
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
