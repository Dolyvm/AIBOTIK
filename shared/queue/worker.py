import os
import logging
from arq.connections import RedisSettings
from arq.cron import cron
from shared.database import get_session
from shared.services.redis_client import get_redis
from shared.queue.tasks import (
    generate_image_task,
    generate_avatar_task,
    expire_subscriptions_task,
    auto_renew_subscriptions_task,
)

logger = logging.getLogger(__name__)


async def startup(ctx):
    logger.info("Worker starting up...")
    ctx["get_session"] = get_session
    ctx["redis"] = await get_redis()
    logger.info("Worker startup complete")


async def shutdown(ctx):
    logger.info("Worker shutting down...")


class WorkerSettings:
    functions = [generate_image_task, generate_avatar_task]

    cron_jobs = [
        cron(expire_subscriptions_task, minute=0),  # каждый час
        cron(auto_renew_subscriptions_task, minute=30),  # каждый час в :30
    ]

    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )

    max_jobs = 10
    job_timeout = int(os.getenv("IMAGE_JOB_TIMEOUT", "900"))
    keep_result = 3600

    on_startup = startup
    on_shutdown = shutdown
