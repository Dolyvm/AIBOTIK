import asyncio
import os
import sys
import types

import pytest
from fastapi import HTTPException

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

from backend.api import subscription as subscription_api
from bot.handlers import payments as bot_payments
from shared.services import platega


def test_platega_create_payment_link_uses_headers_and_omits_fixed_method(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "transactionId": "tx-1",
                "status": "PENDING",
                "url": "https://pay.platega.io/?id=tx-1",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            calls["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            calls["url"] = url
            calls["headers"] = headers
            calls["json"] = json
            return FakeResponse()

    monkeypatch.setattr(platega.httpx, "AsyncClient", FakeAsyncClient)

    client = platega.PlategaClient(
        merchant_id="merchant-id",
        secret="secret-key",
        base_url="https://app.platega.io/",
    )
    result = asyncio.run(
        client.create_payment_link(
            amount_rub=799,
            description="Подписка PLUS",
            return_url="https://example.com/?payment=success",
            failed_url="https://example.com/?payment=failed",
            payload="42",
        )
    )

    assert result["transactionId"] == "tx-1"
    assert calls["url"] == "https://app.platega.io/v2/transaction/process"
    assert calls["headers"]["X-MerchantId"] == "merchant-id"
    assert calls["headers"]["X-Secret"] == "secret-key"
    assert calls["json"]["paymentDetails"] == {"amount": 799, "currency": "RUB"}
    assert calls["json"]["payload"] == "42"
    assert "paymentMethod" not in calls["json"]


def test_platega_callback_rejects_invalid_secret(monkeypatch):
    monkeypatch.setattr(subscription_api, "PLATEGA_MERCHANT_ID", "merchant-id")
    monkeypatch.setattr(subscription_api, "PLATEGA_SECRET", "secret-key")

    with pytest.raises(HTTPException) as exc_info:
        subscription_api._validate_platega_callback_headers("merchant-id", "wrong")

    assert exc_info.value.status_code == 401


def test_amount_matches_exact_decimal_amounts():
    assert subscription_api._amount_matches("799.0", 799)
    assert subscription_api._amount_matches(799, 799)
    assert not subscription_api._amount_matches("799.01", 799)
    assert not subscription_api._amount_matches("not-a-number", 799)


def test_telegram_pre_checkout_rejects_non_stars_payment(monkeypatch):
    answers = []

    class FakeSessionManager:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeSubscriptionRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, _payment_id):
            return types.SimpleNamespace(
                provider="platega",
                status="pending",
                user_id=100,
                currency="RUB",
                amount_stars=799,
            )

    class FakeQuery:
        invoice_payload = "42"
        from_user = types.SimpleNamespace(id=100)
        currency = "XTR"
        total_amount = 799

        async def answer(self, **kwargs):
            answers.append(kwargs)

    monkeypatch.setattr(bot_payments, "get_session", lambda: FakeSessionManager())
    monkeypatch.setattr(bot_payments, "SubscriptionRepository", FakeSubscriptionRepository)

    asyncio.run(bot_payments.on_pre_checkout(FakeQuery()))

    assert answers == [{"ok": False, "error_message": "Платёж не прошёл проверку."}]
