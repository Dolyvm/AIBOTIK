import asyncio
import os
import string
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

from shared.services import prompt_builder, prompt_service
from shared.services.prompt_service import COMPACT_RUNTIME_PROMPT_KEYS, DEFAULT_PROMPTS


RUNTIME_PROMPT_LIMITS = {
    "character_prompt_template": 1200,
    "world_prompt_template": 900,
    "common_style_guide": 1100,
    "meta_instruction": 650,
    "meta_instruction_sfw": 650,
    "player_prompt": 650,
    "summary_prompt": 500,
    "sfw_content_restriction": 300,
    "scene_analyzer_prompt": 1800,
    "scene_analyzer_prompt_sfw": 1300,
}


def _format_fields(template: str) -> set[str]:
    fields = set()
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name:
            fields.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return fields


def test_compact_runtime_prompts_are_short_and_known():
    assert COMPACT_RUNTIME_PROMPT_KEYS == set(RUNTIME_PROMPT_LIMITS)

    for key, limit in RUNTIME_PROMPT_LIMITS.items():
        content = DEFAULT_PROMPTS[key]
        assert len(content) <= limit, key
        assert "send_photo" not in content
        assert "6-8" not in content
        assert "800-1100" not in content
        assert "### ХОРОШО ###" not in content
        assert "### ПЛОХО ###" not in content

    assert "Без JSON" not in DEFAULT_PROMPTS["common_style_guide"]
    assert "<meta>" in DEFAULT_PROMPTS["meta_instruction"]
    assert '"affinity_change"' not in DEFAULT_PROMPTS["meta_instruction"]
    assert '"arousal_change"' not in DEFAULT_PROMPTS["meta_instruction"]


def test_compact_runtime_prompts_keep_required_placeholders():
    expected = {
        "character_prompt_template": {
            "char_name",
            "user_name",
            "description",
            "personality",
            "scenario",
            "relationship_role",
            "preferences",
            "summary",
            "location",
            "heat_context",
            "mood",
            "behavior_instruction",
            "modifier_text",
            "common_style_guide",
            "meta_instruction",
        },
        "world_prompt_template": {
            "world_name",
            "user_name",
            "world_description",
            "summary",
            "location",
            "common_style_guide",
            "meta_instruction",
        },
        "player_prompt": {
            "user_name",
            "character_name",
            "last_character_message",
            "style_examples",
        },
        "summary_prompt": {
            "context_name",
            "existing_summary",
            "heat_context",
            "mood",
            "messages",
        },
        "scene_analyzer_prompt": {
            "character_name",
            "model_type",
            "formatted_chat",
            "mood",
            "heat_context",
            "current_location",
            "available_outfits",
            "gender_possessive",
            "nsfw_level_3_desc",
        },
        "scene_analyzer_prompt_sfw": {
            "character_name",
            "model_type",
            "formatted_chat",
            "mood",
            "heat_context",
            "current_location",
            "available_outfits",
        },
    }

    for key, fields in expected.items():
        assert fields <= _format_fields(DEFAULT_PROMPTS[key]), key


def test_built_story_prompts_do_not_reintroduce_old_verbose_sections(monkeypatch):
    async def fake_get_prompt(key):
        return DEFAULT_PROMPTS[key]

    monkeypatch.setattr(prompt_builder, "get_prompt", fake_get_prompt)

    chat = types.SimpleNamespace(
        affinity=35,
        arousal=10,
        state_meta={"heat_level": 2},
        current_mood="neutral",
        current_location="cafe",
    )
    character = {
        "id": "compact_test_character",
        "name": "Мария",
        "description": "Спокойная собеседница.",
        "personality": "Внимательная и ироничная.",
        "scenario": "Встреча в кафе.",
        "visual": {
            "gender": "female",
            "llm_settings": {
                "relationship_role": "знакомая",
                "preferences": ["диалог"],
            },
        },
    }
    world = {
        "name": "Город",
        "description": "Современный город с тайнами.",
        "gm_instructions": "Поддерживать напряжение.",
        "intro_message": "Начало уже показано.",
    }

    character_prompt = asyncio.run(
        prompt_builder.build_character_prompt(character, chat, user_name="Alex")
    )
    world_prompt = asyncio.run(
        prompt_builder.build_world_prompt(world, user_name="Alex", location="street")
    )
    player_prompt = asyncio.run(
        prompt_builder.build_player_prompt(
            character_name="Мария",
            last_character_message="Она ждёт ответа.",
            chat_history=[],
            user_name="Alex",
        )
    )

    combined = "\n".join([character_prompt, world_prompt, player_prompt])
    assert "3-5 коротких абзацев" in character_prompt
    assert "3-5 коротких абзацев" in world_prompt
    assert "heat_level 2" in character_prompt
    assert '"affinity_change"' not in character_prompt
    assert '"arousal_change"' not in character_prompt
    assert "6-8" not in combined
    assert "800-1100" not in combined
    assert "send_photo" not in combined
    assert "### СТРОГИЙ КОНТРОЛЬ" not in combined


def test_blank_compact_runtime_prompt_falls_back_to_default(monkeypatch):
    cached = {}

    class FakeCache:
        async def get_prompt(self, _key):
            return None

        async def set_prompt(self, key, content):
            cached[key] = content

    monkeypatch.setattr(prompt_service, "_prompt_cache", {"meta_instruction": ""})
    monkeypatch.setattr(prompt_service, "get_cache", lambda: FakeCache())

    content = asyncio.run(prompt_service.get_prompt("meta_instruction"))

    assert content == DEFAULT_PROMPTS["meta_instruction"]
    assert prompt_service._prompt_cache["meta_instruction"] == DEFAULT_PROMPTS["meta_instruction"]
    assert cached == {"meta_instruction": DEFAULT_PROMPTS["meta_instruction"]}


def test_sync_compact_updates_only_whitelisted_prompts(monkeypatch):
    import scripts.init_prompts as init_prompts_module

    compact_prompt = types.SimpleNamespace(key="common_style_guide", content="old compact")
    image_prompt = types.SimpleNamespace(key="anime_base_positive", content="old image")

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [compact_prompt, image_prompt]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, _statement):
            return FakeResult()

        def add(self, _prompt):
            raise AssertionError("test data should not create prompts")

        async def commit(self):
            self.committed = True

    cleared = {"value": False}
    cached = {}

    async def fake_clear_cache():
        cleared["value"] = True

    class FakeCache:
        async def set_prompt(self, key, content):
            cached[key] = content

    monkeypatch.setattr(
        init_prompts_module,
        "DEFAULT_PROMPTS",
        {
            "common_style_guide": "new compact",
            "anime_base_positive": "new image",
        },
    )
    monkeypatch.setattr(
        init_prompts_module,
        "PROMPT_METADATA",
        {
            "common_style_guide": {"category": "character", "name": "Common"},
            "anime_base_positive": {"category": "image", "name": "Anime"},
        },
    )
    monkeypatch.setattr(
        init_prompts_module,
        "COMPACT_RUNTIME_PROMPT_KEYS",
        frozenset({"common_style_guide"}),
    )
    monkeypatch.setattr(init_prompts_module, "get_session", lambda: FakeSession())
    monkeypatch.setattr(init_prompts_module, "clear_cache", fake_clear_cache)
    monkeypatch.setattr(init_prompts_module, "get_cache", lambda: FakeCache())

    asyncio.run(init_prompts_module.init_prompts(sync_compact=True))

    assert compact_prompt.content == "new compact"
    assert image_prompt.content == "old image"
    assert cleared["value"] is True
    assert cached == {"common_style_guide": "new compact"}


def test_sync_image_safety_updates_only_image_safety_prompts(monkeypatch):
    import scripts.init_prompts as init_prompts_module

    scene_prompt = types.SimpleNamespace(key="scene_analyzer_prompt", content="old scene")
    nsfw_prompt = types.SimpleNamespace(key="nsfw_level_2", content="old nsfw")
    image_prompt = types.SimpleNamespace(key="anime_base_positive", content="old image")

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [scene_prompt, nsfw_prompt, image_prompt]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, _statement):
            return FakeResult()

        def add(self, _prompt):
            raise AssertionError("test data should not create prompts")

        async def commit(self):
            self.committed = True

    cleared = {"value": False}
    cached = {}

    async def fake_clear_cache():
        cleared["value"] = True

    class FakeCache:
        async def set_prompt(self, key, content):
            cached[key] = content

    monkeypatch.setattr(
        init_prompts_module,
        "DEFAULT_PROMPTS",
        {
            "scene_analyzer_prompt": "new scene",
            "nsfw_level_2": "new nsfw",
            "anime_base_positive": "new image",
        },
    )
    monkeypatch.setattr(
        init_prompts_module,
        "PROMPT_METADATA",
        {
            "scene_analyzer_prompt": {"category": "scene_analysis", "name": "Scene"},
            "nsfw_level_2": {"category": "image", "name": "NSFW2"},
            "anime_base_positive": {"category": "image", "name": "Anime"},
        },
    )
    monkeypatch.setattr(
        init_prompts_module,
        "IMAGE_SAFETY_PROMPT_KEYS",
        frozenset({"scene_analyzer_prompt", "nsfw_level_2"}),
    )
    monkeypatch.setattr(init_prompts_module, "get_session", lambda: FakeSession())
    monkeypatch.setattr(init_prompts_module, "clear_cache", fake_clear_cache)
    monkeypatch.setattr(init_prompts_module, "get_cache", lambda: FakeCache())

    asyncio.run(init_prompts_module.init_prompts(sync_image_safety=True))

    assert scene_prompt.content == "new scene"
    assert nsfw_prompt.content == "new nsfw"
    assert image_prompt.content == "old image"
    assert cleared["value"] is True
    assert cached == {
        "scene_analyzer_prompt": "new scene",
        "nsfw_level_2": "new nsfw",
    }
