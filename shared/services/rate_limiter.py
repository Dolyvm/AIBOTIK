import time
import logging
from typing import Optional
from redis import asyncio as aioredis

logger = logging.getLogger(__name__)

class RateLimitExceeded(Exception):
    def __init__(self, limit: int, window: int, retry_after: int):
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded: {limit} requests per {window}s. Retry after {retry_after}s")

class RateLimiter:

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int,
        increment: bool = True
    ) -> tuple[bool, int, int]:
        now = time.time()
        window_start = now - window
        full_key = f"ratelimit:{key}"

        try:
            pipe = self.redis.pipeline()

            pipe.zremrangebyscore(full_key, 0, window_start)

            pipe.zcard(full_key)

            results = await pipe.execute()
            current_count = results[1]

            if current_count >= limit:
                oldest = await self.redis.zrange(full_key, 0, 0, withscores=True)
                if oldest:
                    oldest_time = oldest[0][1]
                    retry_after = int(oldest_time + window - now) + 1
                else:
                    retry_after = window

                logger.warning(f"Rate limit exceeded for {key}: {current_count}/{limit}")
                return False, 0, retry_after

            if increment:
                await self.redis.zadd(full_key, {str(now): now})
                await self.redis.expire(full_key, window + 1)
                current_count += 1

            remaining = max(0, limit - current_count)
            reset_time = window

            logger.debug(f"Rate limit OK for {key}: {current_count}/{limit}, remaining: {remaining}")
            return True, remaining, reset_time

        except Exception as e:
            logger.error(f"Rate limit error for {key}: {e}")
            return True, limit, window

    async def is_allowed(self, key: str, limit: int, window: int) -> bool:
        allowed, _, _ = await self.check_rate_limit(key, limit, window)
        return allowed

    async def check_and_raise(self, key: str, limit: int, window: int) -> None:
        allowed, _, retry_after = await self.check_rate_limit(key, limit, window)
        if not allowed:
            raise RateLimitExceeded(limit, window, retry_after)

    async def check_llm_rate_limit(self, telegram_id: int) -> bool:
        limits = RATE_LIMITS["llm"]
        return await self.is_allowed(
            key=f"llm:user:{telegram_id}",
            limit=limits["limit"],
            window=limits["window"]
        )

    async def check_image_rate_limit(self, telegram_id: int) -> bool:
        limits = RATE_LIMITS["images"]
        return await self.is_allowed(
            key=f"images:user:{telegram_id}",
            limit=limits["limit"],
            window=limits["window"]
        )

    async def check_api_rate_limit(self, endpoint: str, telegram_id: int) -> bool:
        limits = RATE_LIMITS.get(endpoint, RATE_LIMITS["chat_send"])
        return await self.is_allowed(
            key=f"api:{endpoint}:user:{telegram_id}",
            limit=limits["limit"],
            window=limits["window"]
        )

    async def get_remaining(self, key: str, limit: int, window: int) -> int:
        _, remaining, _ = await self.check_rate_limit(key, limit, window, increment=False)
        return remaining

RATE_LIMITS = {
    "llm": {"limit": 20, "window": 60, "retry_after": 60},
    "images": {"limit": 50, "window": 3600, "retry_after": 60},
    "chat_send": {"limit": 30, "window": 60, "retry_after": 30},
    "chat_auto_continue": {"limit": 10, "window": 60, "retry_after": 60},
    "characters": {"limit": 60, "window": 60, "retry_after": 30},
    "character_creation": {"limit": 5, "window": 3600, "retry_after": 300},                      
}

_rate_limiter: Optional[RateLimiter] = None

def get_rate_limiter() -> Optional[RateLimiter]:
    return _rate_limiter

def set_rate_limiter(rate_limiter: RateLimiter) -> None:
    global _rate_limiter
    _rate_limiter = rate_limiter
