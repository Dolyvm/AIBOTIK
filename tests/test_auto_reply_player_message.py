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

from shared.services import prompt_builder
from shared.services.context_manager import (
    ContextManager,
    PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT,
    _build_chat_updates_from_meta,
    _clean_generated_player_message,
    _invalid_player_message_reason,
)
from shared.services.llm import LLMResponse


def test_clean_generated_player_message_strips_player_label_and_meta():
    raw = '<meta>{"affinity_change": 1}</meta>\nИгрок: — Конечно, — ответил я.'

    cleaned = _clean_generated_player_message(raw)

    assert cleaned == "— Конечно, — ответил я."
    assert _invalid_player_message_reason(cleaned) is None


def test_invalid_player_message_rejects_character_response_shape():
    raw = "— Пришёл, конечно, — ответила она, медленно улыбаясь."
    cleaned = _clean_generated_player_message(raw)

    assert _invalid_player_message_reason(cleaned) == "character_attribution"


def test_invalid_player_message_rejects_system_prompt_leak():
    raw = "### РОЛЬ ###\nТы генерируешь следующее действие или реплику игрока."
    cleaned = _clean_generated_player_message(raw)

    assert _invalid_player_message_reason(cleaned) == "system_marker"


def test_invalid_player_message_rejects_recent_user_duplicate():
    raw = "Ну, Айко... я, конечно, никому не скажу, но давай глянем, что там у тебя."
    cleaned = _clean_generated_player_message(raw)

    reason = _invalid_player_message_reason(
        cleaned,
        recent_user_messages=[
            "Ну, Айко... я, конечно, никому не скажу, но давай глянем, что там у тебя!"
        ],
    )

    assert reason == "duplicate_user_message"


def test_build_player_prompt_appends_guard_to_database_template(monkeypatch):
    async def fake_get_prompt(key):
        assert key == "player_prompt"
        return (
            "OLD {user_name} {character_name}\n"
            "{last_character_message}\n"
            "{style_examples}"
        )

    monkeypatch.setattr(prompt_builder, "get_prompt", fake_get_prompt)

    prompt = asyncio.run(
        prompt_builder.build_player_prompt(
            character_name="Мария",
            last_character_message="Она посмотрела на игрока.",
            chat_history=[],
            user_name="Alex",
        )
    )

    assert "OLD Alex Мария" in prompt
    assert "Контроль автоответа" in prompt
    assert "Не пиши за персонажа" in prompt
    assert "не повторяй прошлые сообщения игрока" in prompt


def test_generate_player_action_retries_rejected_character_response():
    class FakePlayerLLM:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return LLMResponse("— Пришёл, конечно, — ответила она.")
            return LLMResponse("Игрок: Я смотрю внимательнее и тихо отвечаю: «Продолжай.»")

    manager = ContextManager.__new__(ContextManager)
    manager.player_llm = FakePlayerLLM()

    action = asyncio.run(manager._generate_player_action("PLAYER TASK"))

    assert action == "Я смотрю внимательнее и тихо отвечаю: «Продолжай.»"
    assert len(manager.player_llm.calls) == 2
    assert manager.player_llm.calls[0]["system_prompt"] == PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT
    assert manager.player_llm.calls[0]["messages"] == [{"role": "user", "content": "PLAYER TASK"}]
    assert "ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ОТКЛОНЁН" in manager.player_llm.calls[1]["messages"][0]["content"]


def test_generate_player_action_retries_duplicate_user_message():
    class FakePlayerLLM:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return LLMResponse("Я внимательно смотрю на неё.")
            return LLMResponse("Я осторожно спрашиваю: «Что ты скрываешь?»")

    manager = ContextManager.__new__(ContextManager)
    manager.player_llm = FakePlayerLLM()

    action = asyncio.run(
        manager._generate_player_action(
            "PLAYER TASK WITH STYLE EXAMPLES",
            recent_user_messages=["Я внимательно смотрю на неё."],
            last_character_message="Она прячет за спиной маленький свёрток.",
        )
    )

    assert action == "Я осторожно спрашиваю: «Что ты скрываешь?»"
    assert len(manager.player_llm.calls) == 2
    retry_prompt = manager.player_llm.calls[1]["messages"][0]["content"]
    assert "duplicate_user_message" in retry_prompt
    assert "Она прячет за спиной маленький свёрток." in retry_prompt
    assert "PLAYER TASK WITH STYLE EXAMPLES" not in retry_prompt


def test_meta_updates_ignore_legacy_affinity_arousal_changes():
    chat = types.SimpleNamespace(
        affinity=60,
        arousal=40,
        current_mood="neutral",
        current_location="library",
        state_meta={"heat_level": 2},
    )

    updates = _build_chat_updates_from_meta(
        chat,
        {
            "affinity_change": 20,
            "arousal_change": 15,
            "mood": "curious",
            "thought": "Она хочет узнать больше.",
            "new_location": "classroom",
            "new_action": "opens_notebook",
        },
    )

    assert "affinity" not in updates
    assert "arousal" not in updates
    assert updates["current_mood"] == "curious"
    assert updates["current_location"] == "classroom"
    assert updates["state_meta"] == {
        "heat_level": 2,
        "thought": "Она хочет узнать больше.",
        "action": "opens_notebook",
    }
