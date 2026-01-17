import asyncio
import logging
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.repository import init_db
from handlers import commands, messages, webapp
import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Initializing database...")
    await init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    webapp_url = os.getenv("WEBAPP_URL")

    dp.include_router(commands.router)
    dp.include_router(webapp.router)
    dp.include_router(messages.router)

    
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Меню",
            web_app=WebAppInfo(url=f"{webapp_url}?user_id={{user_id}}")
        )
    )

    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
