import asyncio
import logging
import sys
import subprocess
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo

from bot.handlers import commands, messages, webapp
from bot import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def run_migrations_and_seed():
    logger.info("🔄 Running database migrations...")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd="/app",  
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("✅ Migrations completed successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Migration failed:\n{e.stderr}")
        raise e  

    logger.info("🌱 Seeding content (characters & worlds)...")
    try:
        seed_script_path = "/app/scripts/seed_content.py"
        
        if not os.path.exists(seed_script_path):
            logger.warning(f"⚠️ Seed script not found at {seed_script_path}, skipping.")
            return

        seed_result = subprocess.run(
            ["python", seed_script_path],
            cwd="/app",
            capture_output=True,
            text=True,
            check=True
        )
        
        logger.info("✅ Content seeded successfully!")
        if seed_result.stdout:
            for line in seed_result.stdout.splitlines():
                if line.strip():
                    logger.info(f"[SEED] {line}")
                    
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Seeding failed:\n{e.stderr}")
        # Не роняем бота из-за ошибки сида, но логируем это
    except Exception as e:
        logger.error(f"❌ Unexpected error during seeding: {e}")


async def main():
    # Сначала запускаем миграции и сид
    await run_migrations_and_seed()

    logger.info("🤖 Initializing bot...")

    # Инициализация бота
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Регистрация роутеров
    dp.include_router(commands.router)
    dp.include_router(webapp.router)
    dp.include_router(messages.router)

    # Настройка кнопки WebApp
    webapp_url = config.WEBAPP_URL
    if webapp_url:
        logger.info(f"🔗 Setting WebApp URL: {webapp_url}")
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Меню",
                web_app=WebAppInfo(url=webapp_url)
            )
        )
    else:
        logger.warning("⚠️ WEBAPP_URL is not set in env vars! Menu button might not work.")

    # Удаляем вебхук и запускаем поллинг (очищаем очередь старых апдейтов)
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("🚀 Bot started polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")