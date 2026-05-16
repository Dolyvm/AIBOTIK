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

from shared.services import context_manager as context_manager_module
from shared.services.context_manager import ContextManager, _MetaStreamFilter
from shared.services.llm import LLMClient, LLMStreamEvent


def test_llm_stream_generate_reads_sse_chunks(monkeypatch):
    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            yield 'data: {"id":"gen_1","model":"deepseek/deepseek-v4-flash","choices":[{"delta":{"content":"При"}}]}'
            yield 'data: {"id":"gen_1","model":"deepseek/deepseek-v4-flash","choices":[{"delta":{"content":"вет"},"finish_reason":"stop"}],"usage":{"completion_tokens":2}}'
            yield "data: [DONE]"

    class FakeHTTPClient:
        def __init__(self):
            self.request_kwargs = None

        def stream(self, _method, _url, **kwargs):
            self.request_kwargs = kwargs
            return FakeStreamResponse()

    fake_http = FakeHTTPClient()
    monkeypatch.setattr(LLMClient, "_http_client", fake_http)

    client = LLMClient(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash",
        max_retries=1,
    )

    async def collect_events():
        return [
            event
            async for event in client.stream_generate(
                system_prompt="system",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=20,
            )
        ]

    events = asyncio.run(collect_events())

    assert fake_http.request_kwargs["json"]["stream"] is True
    assert "".join(event.content for event in events) == "Привет"
    assert events[-1].finish_reason == "stop"
    assert events[-1].usage["completion_tokens"] == 2


def test_meta_stream_filter_hides_split_meta_and_releases_text():
    stream_filter = _MetaStreamFilter()

    chunks = [
        stream_filter.feed("<me"),
        stream_filter.feed('ta>{"mood":"neutral","thought":"Мысль","new_location":null,"new_action":null}</meta>\n\nПер'),
        stream_filter.feed("вая строка."),
        stream_filter.finish(),
    ]

    assert "".join(chunks) == "Первая строка."


def test_process_turn_stream_saves_clean_text_after_completion(monkeypatch):
    saved_messages = []
    metric_updates = []

    class FakeSessionManager:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeMessageRepository:
        def __init__(self, _session):
            pass

        async def add(self, chat_id, role, content, tokens_used=0, is_auto_generated=False):
            saved_messages.append(
                {
                    "chat_id": chat_id,
                    "role": role,
                    "content": content,
                    "tokens_used": tokens_used,
                    "is_auto_generated": is_auto_generated,
                }
            )
            return types.SimpleNamespace()

        async def get_history(self, _chat_id, limit=20):
            return [
                types.SimpleNamespace(
                    role=types.SimpleNamespace(value=message["role"]),
                    content=message["content"],
                )
                for message in saved_messages[-limit:]
            ]

    class FakeChatRepository:
        def __init__(self, _session):
            pass

        async def update_metrics(self, chat_id, updates):
            metric_updates.append({"chat_id": chat_id, "updates": updates})

    class FakeLLM:
        async def stream_generate(self, **_kwargs):
            yield LLMStreamEvent(content="<meta>{")
            yield LLMStreamEvent(
                content='"mood":"warm","thought":"Она спокойна.","new_location":"garden","new_action":null}</meta>\n'
            )
            yield LLMStreamEvent(content="Ответ ")
            yield LLMStreamEvent(
                content="персонажа.",
                finish_reason="stop",
                usage={"completion_tokens": 7},
                model="deepseek/deepseek-v4-flash",
                id="gen_1",
            )

    async def fake_build_character_prompt(**_kwargs):
        return "system prompt"

    monkeypatch.setattr(context_manager_module, "get_session", lambda: FakeSessionManager())
    monkeypatch.setattr(context_manager_module, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(context_manager_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(context_manager_module, "build_character_prompt", fake_build_character_prompt)

    chat = types.SimpleNamespace(
        id=42,
        msgs_since_summary=0,
        summary="",
        current_mood="neutral",
        current_location=None,
        state_meta={},
    )
    manager = ContextManager(FakeLLM())

    async def collect_chunks():
        return [
            chunk
            async for chunk in manager.process_turn_stream(
                chat=chat,
                user_input="Привет",
                character={"name": "Мария"},
                user_name="Alex",
            )
        ]

    chunks = asyncio.run(collect_chunks())

    assert "".join(chunks) == "Ответ персонажа."
    assert saved_messages[0]["role"] == "user"
    assert saved_messages[1]["role"] == "assistant"
    assert saved_messages[1]["content"] == "Ответ персонажа."
    assert saved_messages[1]["tokens_used"] == 7
    assert metric_updates[0]["updates"]["current_mood"] == "warm"
    assert metric_updates[0]["updates"]["current_location"] == "garden"
    assert chat.current_mood == "warm"
    assert chat.current_location == "garden"
