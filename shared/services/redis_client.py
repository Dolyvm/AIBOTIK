import os
import logging
from typing import Optional
from redis import asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL")

_redis_pool: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_redis_pool()
    return _redis_pool

async def create_redis_pool() -> aioredis.Redis:
    logger.info(f"Creating Redis connection pool: {REDIS_URL}")
    pool = aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    try:
        await pool.ping()
        logger.info("Redis connection established successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise
    return pool

async def close_redis() -> None:
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection pool closed")

async def health_check() -> bool:
    try:
        redis = await get_redis()
        await redis.ping()
        return True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False
