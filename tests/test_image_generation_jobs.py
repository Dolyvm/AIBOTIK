import asyncio
import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import redis.asyncio  # noqa: F401
except ModuleNotFoundError:
    redis_mod = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_asyncio.Redis = object
    redis_mod.asyncio = redis_asyncio
    sys.modules.setdefault("redis", redis_mod)
    sys.modules.setdefault("redis.asyncio", redis_asyncio)

try:
    import telegram_init_data  # noqa: F401
except ModuleNotFoundError:
    telegram_init_data = types.ModuleType("telegram_init_data")
    telegram_init_data.validate = lambda *_args, **_kwargs: None
    telegram_init_data.parse = lambda *_args, **_kwargs: {}
    sys.modules.setdefault("telegram_init_data", telegram_init_data)


class FakeSessionManager:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def test_generate_image_enqueues_background_job(monkeypatch):
    from backend.api import chat as chat_api

    created_jobs = []
    arq_calls = []
    chat = types.SimpleNamespace(
        id=7,
        user_id=123,
        chat_type="character",
        target_id="char_1",
        state_meta={"heat_level": 2},
    )
    user = types.SimpleNamespace(telegram_id=123)
    message = types.SimpleNamespace(
        role=types.SimpleNamespace(value="user"),
        content="Сделай фото",
    )

    class FakeJobRepo:
        def __init__(self, _session):
            pass

        async def get_active_for_chat(self, _chat_id):
            return None

        async def create_job(self, user_id, chat_id, request_payload):
            job = types.SimpleNamespace(
                id=91,
                user_id=user_id,
                chat_id=chat_id,
                status="queued",
                request_payload=request_payload,
                image_id=None,
                error_message=None,
            )
            created_jobs.append(job)
            return job

        async def set_arq_job_id(self, job_id, arq_job_id):
            created_jobs[-1].arq_job_id = arq_job_id
            return created_jobs[-1]

        async def mark_failed(self, *_args, **_kwargs):
            raise AssertionError("job should not fail")

    class FakeMessageRepo:
        def __init__(self, _session):
            pass

        async def get_history(self, _chat_id, limit=5):
            return [message]

    class FakeSubscription:
        async def check_usage_allowed(self, *_args, **_kwargs):
            return True, 10, 20

    class FakeArqPool:
        async def enqueue_job(self, *args, **kwargs):
            arq_calls.append((args, kwargs))
            return types.SimpleNamespace(job_id=kwargs["_job_id"])

    async def fake_verify(_chat_id, _user):
        return chat

    async def fake_get_character(_target_id):
        return {"id": "char_1", "model_type": "anime"}

    monkeypatch.setattr(chat_api, "get_rate_limiter", lambda: None)
    monkeypatch.setattr(chat_api, "verify_chat_ownership", fake_verify)
    monkeypatch.setattr(chat_api, "get_subscription_service", lambda: FakeSubscription())
    monkeypatch.setattr(chat_api, "get_character", fake_get_character)
    monkeypatch.setattr(chat_api, "get_session", lambda: FakeSessionManager(object()))
    monkeypatch.setattr(chat_api, "ImageGenerationJobRepository", FakeJobRepo)
    monkeypatch.setattr(chat_api, "MessageRepository", FakeMessageRepo)

    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(arq_pool=FakeArqPool())))

    response = asyncio.run(chat_api.generate_image(7, request, user))
    body = json.loads(response.body)

    assert response.status_code == 202
    assert body == {"job_id": 91, "status": "queued"}
    assert arq_calls == [(("generate_chat_image_task", 91), {"_job_id": "chat-image-generation:91"})]
    assert created_jobs[0].request_payload["recent_messages"] == [
        {"role": "user", "content": "Сделай фото"}
    ]
    assert created_jobs[0].request_payload["chat_state"] == {"heat_level": 2}


def test_generate_chat_image_task_marks_success(monkeypatch):
    from shared.queue import tasks

    job = types.SimpleNamespace(
        id=10,
        user_id=123,
        chat_id=7,
        status="queued",
        request_payload={
            "character": {"id": "char_1", "model_type": "anime"},
            "recent_messages": [{"role": "user", "content": "hi"}],
            "chat_state": {"heat_level": 1},
        },
        image_id=None,
    )
    user = types.SimpleNamespace(telegram_id=123)
    chat = types.SimpleNamespace(id=7)
    incremented = []
    tracked = []

    class FakeSession:
        async def get(self, model, entity_id, **_kwargs):
            if model is tasks.ImageGenerationJob and entity_id == job.id:
                return job
            if model is tasks.User and entity_id == user.telegram_id:
                return user
            if model is tasks.Chat and entity_id == chat.id:
                return chat
            return None

        async def rollback(self):
            pass

    class FakeJobRepo:
        def __init__(self, _session):
            pass

        async def get_by_id(self, job_id):
            return job if job_id == job.id else None

        async def mark_running(self, job_id):
            assert job_id == job.id
            job.status = "running"
            return job

        async def mark_succeeded(self, job_id, image_id):
            assert job_id == job.id
            job.status = "succeeded"
            job.image_id = image_id
            return job

    class FakePhotoService:
        async def generate_for_chat(self, **kwargs):
            await kwargs["before_save"]()
            return types.SimpleNamespace(id=44)

    class FakeSubscription:
        async def increment_usage(self, user_id, usage_type, _session):
            incremented.append((user_id, usage_type))

    async def fake_track(_session, **kwargs):
        tracked.append(kwargs)

    monkeypatch.setattr(tasks, "ImageGenerationJobRepository", FakeJobRepo)
    monkeypatch.setattr(tasks, "PhotoGenerationService", lambda: FakePhotoService())
    monkeypatch.setattr(tasks, "get_subscription_service", lambda: FakeSubscription())
    monkeypatch.setattr(tasks.AnalyticsService, "track", fake_track)

    result = asyncio.run(
        tasks.generate_chat_image_task(
            {"get_session": lambda: FakeSessionManager(FakeSession())},
            job.id,
        )
    )

    assert result == {"status": "succeeded", "job_id": 10, "image_id": 44}
    assert job.status == "succeeded"
    assert job.image_id == 44
    assert incremented == [(123, "images_generated")]
    assert tracked[0]["meta"]["job_id"] == 10


def test_generate_chat_image_task_marks_provider_failure_without_usage(monkeypatch):
    from shared.queue import tasks

    job = types.SimpleNamespace(
        id=10,
        user_id=123,
        chat_id=7,
        status="queued",
        request_payload={
            "character": {"id": "char_1"},
            "recent_messages": [],
            "chat_state": {},
        },
        image_id=None,
    )
    user = types.SimpleNamespace(telegram_id=123)
    chat = types.SimpleNamespace(id=7)
    incremented = []

    class FakeSession:
        async def get(self, model, entity_id, **_kwargs):
            if model is tasks.ImageGenerationJob and entity_id == job.id:
                return job
            if model is tasks.User and entity_id == user.telegram_id:
                return user
            if model is tasks.Chat and entity_id == chat.id:
                return chat
            return None

        async def rollback(self):
            pass

    class FakeJobRepo:
        def __init__(self, _session):
            pass

        async def get_by_id(self, job_id):
            return job if job_id == job.id else None

        async def mark_running(self, job_id):
            assert job_id == job.id
            job.status = "running"
            return job

        async def mark_failed(self, job_id, error_code, error_message):
            assert job_id == job.id
            job.status = "failed"
            job.error_code = error_code
            job.error_message = error_message
            return job

    class FakePhotoService:
        async def generate_for_chat(self, **_kwargs):
            raise tasks.PhotoProviderError("provider is down")

    class FakeSubscription:
        async def increment_usage(self, user_id, usage_type, _session):
            incremented.append((user_id, usage_type))

    monkeypatch.setattr(tasks, "ImageGenerationJobRepository", FakeJobRepo)
    monkeypatch.setattr(tasks, "PhotoGenerationService", lambda: FakePhotoService())
    monkeypatch.setattr(tasks, "get_subscription_service", lambda: FakeSubscription())

    result = asyncio.run(
        tasks.generate_chat_image_task(
            {"get_session": lambda: FakeSessionManager(FakeSession())},
            job.id,
        )
    )

    assert result == {"status": "failed", "job_id": 10, "error": "provider_failed"}
    assert job.status == "failed"
    assert job.error_code == "provider_failed"
    assert incremented == []
