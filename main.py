"""Точка входа приложения."""

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config.settings import Settings
from services.llm_client import OpenRouterClient
from services.prompt_builder import PromptBuilder
from services.state_analyzer import StateAnalyzer
from services.summary_engine import SummaryEngine
from services.character_manager import CharacterManager
from storage.memory import InMemoryStorage
from handlers.messages import MessageHandler, router as message_router
from handlers.commands import router as command_router
from handlers.webapp import router as webapp_router
from web.server import create_app, run_server

# Настройка логирования
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info(f"Logging level set to: {log_level}")


async def main():
    """Основная функция запуска бота."""
    logger.info("Starting Maya Telegram Bot...")

    # Загрузка конфигурации
    try:
        settings = Settings()
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        logger.error("Make sure you have a .env file with required settings.")
        return

    # Инициализация хранилища
    storage = InMemoryStorage()

    # Инициализация LLM клиента
    llm_client = OpenRouterClient(
        api_key=settings.OPENROUTER_API_KEY,
        model=settings.LLM_MODEL,
        default_params={
            "temperature": settings.TEMPERATURE,
            "top_p": settings.TOP_P,
            "max_tokens": settings.MAX_TOKENS,
            "repetition_penalty": settings.REPETITION_PENALTY,
        }
    )

    # Инициализация сервисов
    prompt_builder = PromptBuilder()
    state_analyzer = StateAnalyzer()
    summary_engine = SummaryEngine(
        llm_client=llm_client,
        trigger_every=settings.SUMMARY_TRIGGER_EVERY,
        keep_recent=settings.SUMMARY_KEEP_RECENT
    )

    # Инициализация CharacterManager
    characters_dir = Path(__file__).parent / "characters"
    character_manager = CharacterManager(characters_dir)

    if not character_manager.get_all_characters():
        logger.error("No characters loaded! Please add PNG character cards to characters/ folder")
        return

    # Создание обработчика сообщений
    message_handler = MessageHandler(
        llm_client=llm_client,
        storage=storage,
        character_manager=character_manager,
        summary_engine=summary_engine,
        state_analyzer=state_analyzer,
        prompt_builder=prompt_builder
    )

    # Инициализация бота
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    dp = Dispatcher()

    # Регистрация роутеров
    dp.include_router(command_router)
    dp.include_router(webapp_router)
    dp.include_router(message_router)

    # Передача зависимостей в middleware через router

    # Middleware для передачи handler и storage в обработчики
    @dp.message.middleware()
    async def inject_dependencies(handler, event, data):
        """Middleware для инъекции зависимостей."""
        data["handler"] = message_handler
        data["storage"] = storage
        data["character_manager"] = character_manager
        return await handler(event, data)

    # Создание WebApp сервера
    webapp = create_app(storage, character_manager)

    # Запуск бота и WebApp сервера
    logger.info("Starting bot and WebApp server...")
    try:
        # Запускаем оба сервера параллельно
        await asyncio.gather(
            dp.start_polling(bot),
            run_server(webapp, host="0.0.0.0", port=8080)
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot stopped with error: {e}")
    finally:
        await llm_client.close()
        await bot.session.close()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
