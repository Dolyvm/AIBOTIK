import asyncio
import logging
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher

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

    dp.include_router(commands.router)
    dp.include_router(webapp.router)
    dp.include_router(messages.router)

    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
