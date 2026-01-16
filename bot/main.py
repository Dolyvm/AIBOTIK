import asyncio
import logging
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.repository import init_db
from handlers import commands, messages, webapp
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main bot function"""
    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Initialize bot and dispatcher
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Register routers
    dp.include_router(commands.router)
    dp.include_router(webapp.router)
    dp.include_router(messages.router)

    # Start polling
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
