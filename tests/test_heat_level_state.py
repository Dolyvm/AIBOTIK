import asyncio
import os
import sys
import types

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

from shared import constants


def test_get_heat_level_prefers_state_meta_over_legacy_affinity():
    chat = types.SimpleNamespace(
        affinity=90,
        state_meta={"heat_level": 1},
    )

    assert constants.get_heat_level(chat) == 1
    assert constants.get_heat_context(1).startswith("heat_level 1")


def test_get_modifier_for_stage_uses_heat_level(monkeypatch):
    async def fake_get_prompt(key):
        return {
            "character_modifiers_aiko_stage_1": "stage one|talk",
            "character_modifiers_aiko_stage_2": "stage two|flirt",
            "character_modifiers_aiko_stage_3": "stage three|hug",
            "character_modifiers_aiko_stage_4": "stage four|kiss",
        }[key]

    monkeypatch.setattr(constants, "get_prompt", fake_get_prompt)
    monkeypatch.setattr(constants, "get_cache", lambda: None)

    modifier = asyncio.run(
        constants.get_modifier_for_stage(
            "aiko",
            {"heat_level": 2, "affinity": 0},
        )
    )

    assert modifier == {"instruction": "stage three", "allowed_actions": ["hug"]}
