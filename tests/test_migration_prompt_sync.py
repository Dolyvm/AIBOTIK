import importlib.util
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")

try:
    import redis.asyncio  # noqa: F401
except ModuleNotFoundError:
    redis_mod = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_asyncio.Redis = object
    redis_mod.asyncio = redis_asyncio
    sys.modules.setdefault("redis", redis_mod)
    sys.modules.setdefault("redis.asyncio", redis_asyncio)

from scripts.init_prompts import PROMPT_METADATA
from shared.services.prompt_service import DEFAULT_PROMPTS, PHOTO_PROMPT_KEYS


def _load_sync_migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0008_sync_schema_after_0007.py"
    spec = importlib.util.spec_from_file_location("migration_0008_sync_schema_after_0007", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sync_schema_migration_replaces_removed_photo_migrations():
    migration = _load_sync_migration()

    assert migration.revision == "0008_sync_schema_after_0007"
    assert migration.down_revision == "0007_platega_payments"


def test_sync_schema_migration_photo_prompts_match_runtime_defaults():
    migration = _load_sync_migration()
    rows = {key: (category, name, content) for key, category, name, content in migration.PHOTO_PROMPT_ROWS}

    assert len(rows) == len(migration.PHOTO_PROMPT_ROWS)
    assert set(rows) == PHOTO_PROMPT_KEYS

    for key in PHOTO_PROMPT_KEYS:
        category, name, content = rows[key]
        assert content == DEFAULT_PROMPTS[key]
        assert category == PROMPT_METADATA[key]["category"]
        assert name == PROMPT_METADATA[key]["name"]
