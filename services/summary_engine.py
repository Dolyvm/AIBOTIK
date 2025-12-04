"""Движок для создания и управления summary диалогов."""

import logging
from typing import List, Tuple, Optional

from models.state import CharacterState

logger = logging.getLogger(__name__)


SUMMARY_PROMPT = """Ты — ассистент для создания кратких пересказов ролевых диалогов.

Проанализируй следующий диалог между {user_name} и {char_name} и создай краткое summary.

### ДИАЛОГ ДЛЯ АНАЛИЗА ###
{dialogue_text}

### ТЕКУЩЕЕ СОСТОЯНИЕ ОТНОШЕНИЙ ###
{relationship_state}

### ЗАДАНИЕ ###
Создай структурированное summary на русском языке (150-200 слов):

1. **Ключевые события:** Что произошло? (2-3 пункта)
2. **Эмоциональные моменты:** Важные эмоциональные взаимодействия
3. **Изменения в отношениях:** Как изменились отношения между персонажами?
4. **Текущая ситуация:** Чем закончился этот фрагмент? Что происходит сейчас?

Пиши кратко, фактически, без лишних украшений."""


class SummaryEngine:
    """Движок для создания и управления summary диалогов."""

    def __init__(self, llm_client, trigger_every: int = 20, keep_recent: int = 15):
        """
        Args:
            llm_client: Клиент для LLM (OpenRouterClient)
            trigger_every: Через сколько сообщений создавать summary
            keep_recent: Сколько последних сообщений держать в контексте
        """
        self.llm_client = llm_client
        self.trigger_every = trigger_every
        self.keep_recent = keep_recent

    async def should_summarize(self, message_count: int, has_summary: bool) -> bool:
        """
        Проверяет, нужно ли создавать summary.

        Args:
            message_count: Текущее количество сообщений
            has_summary: Есть ли уже summary

        Returns:
            True, если нужно создать summary
        """
        if not has_summary:
            return message_count >= self.trigger_every
        return message_count % self.trigger_every == 0

    async def create_summary(
        self,
        messages: List[dict],
        char_name: str,
        user_name: str,
        current_state: CharacterState,
        previous_summary: Optional[str] = None
    ) -> str:
        """
        Создаёт новое summary.

        Args:
            messages: Список сообщений для суммаризации
            char_name: Имя персонажа
            user_name: Имя пользователя
            current_state: Текущее состояние персонажа
            previous_summary: Предыдущее summary (если есть)

        Returns:
            Текст summary
        """
        logger.info(f"📝 Creating summary for {len(messages)} messages")

        # Формируем текст диалога для анализа
        dialogue_parts = []
        for msg in messages:
            role = user_name if msg['role'] == 'user' else char_name
            dialogue_parts.append(f"{role}: {msg['content']}")
        dialogue_text = "\n\n".join(dialogue_parts)

        # Если есть предыдущее summary, включаем его
        context = ""
        if previous_summary:
            context = f"### ПРЕДЫДУЩЕЕ SUMMARY ###\n{previous_summary}\n\n"
            logger.info(f"  Using previous summary: {len(previous_summary)} chars")

        prompt = SUMMARY_PROMPT.format(
            user_name=user_name,
            char_name=char_name,
            dialogue_text=dialogue_text,
            relationship_state=current_state.to_prompt_string()
        )

        logger.debug(f"\n{'='*80}\nSUMMARY PROMPT:\n{'='*80}\n{context + prompt}\n{'='*80}")

        # Генерируем summary через LLM
        try:
            response = await self.llm_client.generate(
                messages=[{"role": "user", "content": context + prompt}],
                max_tokens=250,
                temperature=0.3  # Низкая температура для фактичности
            )
            logger.info(f"✅ Summary created: {len(response)} chars")
            logger.info(f"\n{'='*80}\nGENERATED SUMMARY:\n{'='*80}\n{response}\n{'='*80}")
            return response
        except Exception as e:
            logger.error(f"Failed to create summary: {e}")
            # Fallback - возвращаем простое summary
            return f"События последних {len(messages)} сообщений. Отношения: {current_state.relationship_stage.value}."

    def get_context_messages(
        self,
        all_messages: List[dict],
        summary: Optional[str]
    ) -> Tuple[Optional[str], List[dict]]:
        """
        Возвращает summary и недавние сообщения для контекста.

        Args:
            all_messages: Все сообщения в сессии
            summary: Текущее summary (если есть)

        Returns:
            Tuple (summary, recent_messages)
        """
        if len(all_messages) <= self.trigger_every:
            # Достаточно места — отправляем всё без summary
            return None, all_messages

        # Берём последние N сообщений
        recent = all_messages[-self.keep_recent:]
        return summary, recent
