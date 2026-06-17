import os
import logging
from arq.connections import RedisSettings
from arq.cron import cron
from shared.database import get_session
from shared.services.redis_client import get_redis
from shared.services.cache import CacheService, set_cache
from shared.services.prompt_service import init_prompt_cache
from shared.queue.tasks import (
    cancel_stale_image_jobs_task,
    expire_subscriptions_task,
    generate_chat_image_task,
)

logger = logging.getLogger(__name__)


async def startup(ctx):
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().setLevel(log_level)
    logger.info("Worker starting up...")
    ctx["get_session"] = get_session
    redis = await get_redis()
    ctx["redis"] = redis
    set_cache(CacheService(redis))

    try:
        async with get_session() as db:
            await init_prompt_cache(db)
        logger.info("Worker prompt cache initialized")
    except Exception as e:
        logger.error(f"Failed to initialize worker prompt cache: {e}")
        logger.warning("Worker will use default prompts until prompt cache is available")

    logger.info("Worker startup complete")


async def shutdown(ctx):
    logger.info("Worker shutting down...")


class WorkerSettings:
    functions = [generate_chat_image_task, cancel_stale_image_jobs_task]

    cron_jobs = [
        cron(expire_subscriptions_task, minute=0),  # каждый час
        cron(cancel_stale_image_jobs_task, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]

    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )

    max_jobs = 10
    job_timeout = int(os.getenv("WORKER_JOB_TIMEOUT", "600"))
    keep_result = 3600

    on_startup = startup
    on_shutdown = shutdown
