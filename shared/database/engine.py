"""Единственный engine для всего приложения."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from shared.config import DATABASE_URL

POOL_CONFIG = {
    "pool_size": 15,
    "max_overflow": 25,
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "pool_timeout": 10,
}

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    **POOL_CONFIG
)
