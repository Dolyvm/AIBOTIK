from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.sessions import SessionMiddleware
import sys
from pathlib import Path
import os
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from api import characters, worlds, user, chat, webapp, subscription
from api.create_character.cc_routes import router as create_character_router
from api.create_world.cw_routes import router as create_world_router
from admin.router import router as admin_router
from shared.database import get_session
from shared.database.exceptions import (
    EntityNotFoundError,
    ValidationError,
    InsufficientBalanceError,
    UsageLimitExceeded,
)
from shared.services.prompt_service import init_prompt_cache
from shared.services.redis_client import get_redis, close_redis
from shared.services.cache import CacheService, set_cache
from shared.services.rate_limiter import RateLimiter, set_rate_limiter, RateLimitExceeded
from shared.services.subscription import get_subscription_service
from shared.services.llm import LLMClient
from arq import create_pool
from arq.connections import RedisSettings

app = FastAPI(title="AI RP Bot WebApp")

SECRET_KEY = os.getenv("SECRET_KEY")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

@app.exception_handler(EntityNotFoundError)
async def handle_not_found(request, exc: EntityNotFoundError):
    return JSONResponse(
        status_code=404,
        content={
            "error": "not_found",
            "message": exc.message,
            "code": f"{exc.entity_type.upper()}_NOT_FOUND"
        }
    )

@app.exception_handler(ValidationError)
async def handle_validation(request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": exc.message,
            "field": exc.field,
            "code": "VALIDATION_ERROR"
        }
    )

@app.exception_handler(InsufficientBalanceError)
async def handle_balance(request, exc: InsufficientBalanceError):
    return JSONResponse(
        status_code=400,
        content={
            "error": "insufficient_balance",
            "message": exc.message,
            "current_balance": exc.current,
            "required": exc.required,
            "code": "INSUFFICIENT_BALANCE"
        }
    )

@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": str(exc),
            "retry_after": exc.retry_after,
            "code": "RATE_LIMIT_EXCEEDED"
        },
        headers={"Retry-After": str(exc.retry_after)}
    )

@app.exception_handler(UsageLimitExceeded)
async def handle_usage_limit(request, exc: UsageLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "error": "usage_limit_exceeded",
            "message": exc.message,
            "usage_type": exc.usage_type,
            "limit": exc.limit,
            "code": "USAGE_LIMIT_EXCEEDED"
        }
    )

@app.exception_handler(RequestValidationError)
async def handle_request_validation(request, exc: RequestValidationError):
    logging.error(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": exc.errors(),
            "code": "REQUEST_VALIDATION_ERROR"
        }
    )

@app.on_event("startup")
async def startup_event():
    try:
        redis = await get_redis()
        cache = CacheService(redis)
        set_cache(cache)
        rate_limiter = RateLimiter(redis)
        set_rate_limiter(rate_limiter)
        logging.info("Redis cache and rate limiter initialized")
    except Exception as e:
        logging.error(f"Failed to initialize Redis: {e}")
        logging.warning("Application will run without caching")

    try:
        redis_url = os.getenv("REDIS_URL")
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(redis_url))
        logging.info("arq pool initialized for background tasks")
    except Exception as e:
        logging.error(f"Failed to initialize arq pool: {e}")
        logging.warning("Background tasks will be unavailable")
        app.state.arq_pool = None

    try:
        async with get_session() as db:
            await init_prompt_cache(db)
    except Exception as e:
        logging.error(f"Failed to initialize prompt cache: {e}")
        logging.warning("Application will use default prompts")

@app.on_event("shutdown")
async def shutdown_event():
    try:
        if hasattr(app.state, "arq_pool") and app.state.arq_pool:
            await app.state.arq_pool.close()
            logging.info("arq pool closed")
    except Exception as e:
        logging.error(f"Error closing arq pool: {e}")

    try:
        await LLMClient.close_http_client()
    except Exception as e:
        logging.error(f"Error closing LLM http client: {e}")

    try:
        await close_redis()
        logging.info("Redis connection closed")
    except Exception as e:
        logging.error(f"Error closing Redis: {e}")

app.include_router(characters.router)
app.include_router(worlds.router)
app.include_router(user.router)
app.include_router(chat.router)
app.include_router(webapp.router)
app.include_router(create_character_router)
app.include_router(create_world_router)
app.include_router(admin_router)
app.include_router(subscription.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/content", StaticFiles(directory="/app/content"), name="content")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
