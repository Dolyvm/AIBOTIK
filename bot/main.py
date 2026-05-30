import asyncio
import logging
import signal
import sys
import os
import subprocess
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

sys.path.insert(0, str(Path(__file__).parent.parent))

from handlers import commands, messages, payments, webapp
import config
from shared.database import engine
from shared.services.llm import LLMClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

shutdown_flag = asyncio.Event()


def setup_signal_handlers():
    def signal_handler(sig, _):
        sig_name = signal.Signals(sig).name
        logger.info(f"Received signal {sig_name}, initiating shutdown...")
        shutdown_flag.set()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal handlers configured")


async def run_migrations_async():
    logger.info("Running database migrations...")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd="/app",
                capture_output=True,
                text=True,
                check=True
            )
        )
        logger.info("Migrations completed successfully")
        if result.stdout:
            logger.debug(f"Migration output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed: {e.stderr}")
        raise
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


async def cleanup_resources(bot: Bot):
    logger.info("Cleaning up resources...")
    try:
        await LLMClient.close_http_client()
        logger.info("LLM HTTP client closed")
    except Exception as e:
        logger.error(f"Error closing LLM client: {e}")
    try:
        await bot.session.close()
        logger.info("Bot session closed")
    except Exception as e:
        logger.error(f"Error closing bot session: {e}")
    try:
        await engine.dispose()
        logger.info("Database engine disposed")
    except Exception as e:
        logger.error(f"Error disposing database engine: {e}")

    logger.info("All resources cleaned up")


async def main():
    setup_signal_handlers()
    await run_migrations_async()

    logger.info("Initializing bot...")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    webapp_url = os.getenv("WEBAPP_URL")

    dp.include_router(commands.router)
    dp.include_router(payments.router)
    dp.include_router(webapp.router)
    dp.include_router(messages.router)

    webhook_url = os.getenv("WEBHOOK_URL")  
    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook")
    webhook_host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    webhook_port = int(os.getenv("WEBHOOK_PORT", "8443"))

    is_prod = os.getenv("IS_PROD", "false").lower() == "true"

    if is_prod and not webhook_url:
        raise ValueError("WEBHOOK_URL environment variable is required in webhook mode!")

    try:
        if webapp_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Меню",
                    web_app=WebAppInfo(url=f"{webapp_url}?user_id={{user_id}}")
                )
            )
            logger.info("Menu button set to %s", webapp_url)
        else:
            logger.warning("WEBAPP_URL is not set; skipping Telegram menu button setup")

        if is_prod:
            full_webhook_url = f"{webhook_url.rstrip('/')}{webhook_path}"
            await bot.set_webhook(
                url=full_webhook_url,
                drop_pending_updates=False,
                allowed_updates=["message", "pre_checkout_query", "callback_query"],
            )
            logger.info(f"Webhook set to {full_webhook_url}")

            app = web.Application()
            webhook_requests_handler = SimpleRequestHandler(
                dispatcher=dp,
                bot=bot
            )
            webhook_requests_handler.register(app, path=webhook_path)
            setup_application(app, dp, bot=bot)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, webhook_host, webhook_port)
            await site.start()

            logger.info(f"Webhook server started on {webhook_host}:{webhook_port}")
            logger.info("Bot is running, waiting for updates...")

            await shutdown_flag.wait()

            logger.info("Shutdown signal received, stopping bot...")

            await runner.cleanup()
            logger.info("Webhook server stopped")

            await bot.delete_webhook()
            logger.info("Webhook deleted from Telegram")
        else:
            try:
                # Проверяем текущий статус webhook
                webhook_info = await bot.get_webhook_info()
                logger.info(f"Current webhook info: {webhook_info}")

                if webhook_info.url:
                    logger.info(f"Webhook is active: {webhook_info.url}")
                    if not is_prod:
                        # В режиме разработки - удаляем webhook
                        logger.info("Deleting webhook for polling mode...")
                        await bot.delete_webhook(drop_pending_updates=True)
                        logger.info("Webhook deleted successfully")
                else:
                    logger.info("No active webhook found")

            except Exception as e:
                logger.error(f"Error checking/deleting webhook: {e}")
            logger.info("Local Env detected...")
            await dp.start_polling(bot)
            logger.info("Started bot with long polling")

    except Exception as e:
        logger.error(f"Error in main loop: {e}", exc_info=True)
        raise
    finally:
        await cleanup_resources(bot)
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
