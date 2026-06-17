import asyncio
import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")

from shared.services.llm import LLMClient


def test_deepseek_payload_ignores_alibaba_by_default():
    client = LLMClient(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash",
    )

    _, payload = asyncio.run(
        client._build_payload(
            system_prompt="system",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=20,
        )
    )

    assert payload["provider"]["ignore"] == ["alibaba"]


def test_deepseek_payload_preserves_provider_preferences_and_existing_ignores():
    provider = {"sort": "throughput", "ignore": ["deepinfra"]}
    client = LLMClient(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash",
        provider=provider,
    )

    _, payload = asyncio.run(
        client._build_payload(
            system_prompt="system",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=20,
        )
    )

    assert payload["provider"] == {
        "sort": "throughput",
        "ignore": ["deepinfra", "alibaba"],
    }
    assert provider == {"sort": "throughput", "ignore": ["deepinfra"]}


def test_deepseek_payload_applies_alibaba_ignore_after_extra_payload_provider_override():
    client = LLMClient(
        api_key="test-key",
        model="deepseek/deepseek-v4-flash",
        provider={"sort": "throughput"},
    )

    _, payload = asyncio.run(
        client._build_payload(
            system_prompt="system",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=20,
            extra_payload={"provider": {"sort": "latency", "ignore": ["openai"]}},
        )
    )

    assert payload["provider"] == {
        "sort": "latency",
        "ignore": ["openai", "alibaba"],
    }


def test_qwen_payload_keeps_alibaba_available():
    provider = {"sort": "throughput"}
    client = LLMClient(
        api_key="test-key",
        model="qwen/qwen3.6-flash",
        provider=provider,
    )

    _, payload = asyncio.run(
        client._build_payload(
            system_prompt="system",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=20,
        )
    )

    assert payload["provider"] == {"sort": "throughput"}
    assert provider == {"sort": "throughput"}
