"""Обработчик текстовых сообщений."""

import logging
from aiogram import Router, F
from aiogram.types import Message

from services.llm_client import OpenRouterClient
from services.prompt_builder import PromptBuilder
from services.state_analyzer import StateAnalyzer
from services.summary_engine import SummaryEngine
from services.character_manager import CharacterManager
from storage.memory import InMemoryStorage
from utils.helpers import format_response

logger = logging.getLogger(__name__)

router = Router()


class MessageHandler:
    """Основной обработчик текстовых сообщений от пользователей."""

    def __init__(
        self,
        llm_client: OpenRouterClient,
        storage: InMemoryStorage,
        character_manager: CharacterManager,
        summary_engine: SummaryEngine,
        state_analyzer: StateAnalyzer,
        prompt_builder: PromptBuilder
    ):
        self.llm = llm_client
        self.storage = storage
        self.character_manager = character_manager
        self.summary_engine = summary_engine
        self.state_analyzer = state_analyzer
        self.prompt_builder = prompt_builder

    async def handle_message(self, message: Message):
        """
        Основной обработчик входящих сообщений.

        Args:
            message: Сообщение от пользователя
        """
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "User"
        user_text = message.text

        logger.info(f"Processing message from user {user_id}: {user_text[:50]}...")

        # 1. Получаем сессию пользователя
        session = await self.storage.get_session(user_id, user_name)

        # 1.5. Получаем данные текущего персонажа
        character = self.character_manager.get_character(session.current_character)
        if not character:
            await message.answer(
                f"Персонаж '{session.current_character}' не найден!\n"
                "Используй /character чтобы выбрать персонажа."
            )
            return

        # 2. Анализируем сообщение и обновляем состояние
        state_update = self.state_analyzer.analyze_user_message(
            user_text,
            session.character_state
        )
        session.character_state = self.state_analyzer.apply_update(
            session.character_state,
            state_update
        )

        # 3. Добавляем сообщение пользователя в историю
        session.add_message("user", user_text)

        # 4. Проверяем, нужно ли создать summary
        if await self.summary_engine.should_summarize(
            session.message_count,
            session.summary is not None
        ):
            logger.info(f"📝 SUMMARIZATION TRIGGERED for user {user_id}")
            logger.info(f"  Message count: {session.message_count}")
            logger.info(f"  Messages to summarize: {len(session.messages[:-self.summary_engine.keep_recent])}")

            # Создаём summary из старых сообщений (все кроме последних N)
            messages_to_summarize = session.messages[:-self.summary_engine.keep_recent]
            session.summary = await self.summary_engine.create_summary(
                [{"role": m.role, "content": m.content} for m in messages_to_summarize],
                character.name,
                user_name,
                session.character_state,
                session.summary
            )
            session.summary_created_at = session.message_count

            # Уведомляем prompt builder о создании summary (для инвалидации кеша)
            self.prompt_builder.notify_summary_created()

            logger.info(f"✅ Summary created successfully")
            logger.info(f"  Summary length: {len(session.summary)} chars")
            logger.debug(f"  Summary content:\n{session.summary}")

        # 5. Строим системный промпт (с Dynamic Injection)
        system_prompt = self.prompt_builder.build_system_prompt(
            character=character,
            state=session.character_state,
            summary=session.summary,
            user_name=user_name,
            session=session,  # Передаём сессию для Dynamic Injection
            message_count=session.message_count  # Передаём количество сообщений
        )

        logger.info(f"📋 System prompt built:")
        logger.info(f"  Character: {character.name}")
        logger.info(f"  Trust: {session.character_state.trust}, Affection: {session.character_state.affection}")
        logger.info(f"  Mood: {session.character_state.mood.value}")
        logger.info(f"  Has summary: {session.summary is not None}")
        logger.debug(f"\n{'='*80}\nSYSTEM PROMPT:\n{'='*80}\n{system_prompt}\n{'='*80}")

        # 6. Получаем сообщения для контекста
        _, context_messages = self.summary_engine.get_context_messages(
            session.get_messages_for_context(),
            session.summary
        )

        logger.info(f"💬 Context: {len(context_messages)} messages in context")
        logger.debug(f"  Context messages: {context_messages}")

        # 7. Генерируем ответ
        try:
            # Отправляем индикатор "печатает..."
            await message.bot.send_chat_action(message.chat.id, "typing")

            response = await self.llm.generate(
                messages=context_messages,
                system_prompt=system_prompt
            )

            logger.info(f"Generated response for user {user_id}: {len(response)} chars")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error generating response: {error_msg}")

            # Более информативное сообщение об ошибке
            if "404" in error_msg and "No endpoints found" in error_msg:
                user_msg = (
                    "⚠️ Модель LLM временно недоступна.\n\n"
                    "Администратор: проверьте настройку LLM_MODEL в .env файле."
                )
            elif "401" in error_msg or "403" in error_msg:
                user_msg = (
                    "⚠️ Ошибка авторизации API.\n\n"
                    "Администратор: проверьте OPENROUTER_API_KEY в .env файле."
                )
            elif "429" in error_msg:
                user_msg = (
                    "⚠️ Модель перегружена (rate limit).\n\n"
                    "Попробуй ещё раз через 10-30 секунд, или администратор может "
                    "переключиться на другую модель в .env файле."
                )
            else:
                user_msg = (
                    "Извини, произошла ошибка при обработке сообщения. "
                    "Попробуй ещё раз через несколько секунд."
                )

            await message.answer(user_msg)
            return

        # 8. Сохраняем ответ в историю
        session.add_message("assistant", response)

        # 9. Применяем форматирование и отправляем ответ пользователю
        formatted_response = format_response(response)
        await message.answer(formatted_response, parse_mode="HTML")

        logger.info(f"Successfully handled message for user {user_id}")


# Регистрация обработчика
@router.message(F.text)
async def on_text_message(message: Message, handler: MessageHandler):
    """Точка входа для текстовых сообщений."""
    await handler.handle_message(message)
