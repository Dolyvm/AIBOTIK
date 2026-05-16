import asyncio
import os
import sys
import types

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")

fal_client_mod = types.ModuleType("fal_client")
sys.modules.setdefault("fal_client", fal_client_mod)

from shared.services import image_provider


def test_compose_real_prompt_omits_negative_terms_when_sfw():
    prompt = image_provider._compose_real_prompt(
        "photorealistic adult woman portrait",
        "nudity, nsfw, penis",
        allow_nsfw=False,
    )

    assert prompt == "photorealistic adult woman portrait"
    assert "Do not depict" not in prompt
    assert "nudity" not in prompt
    assert "nsfw" not in prompt
    assert "penis" not in prompt


def test_compose_real_prompt_omits_negative_terms_when_nsfw_allowed():
    prompt = image_provider._compose_real_prompt(
        "photorealistic adult woman portrait",
        "male, penis, testicles, bulge",
        allow_nsfw=True,
    )

    assert prompt == "photorealistic adult woman portrait"
    assert "Do not depict" not in prompt
    assert "penis" not in prompt
    assert "testicles" not in prompt
    assert "bulge" not in prompt


def test_submit_real_avatar_sends_sfw_safe_fal_arguments(monkeypatch):
    captured = {}

    class Handler:
        async def get(self):
            return {"images": [{"url": "https://example.test/avatar.png"}]}

    async def fake_submit_async(model_id, arguments):
        captured["model_id"] = model_id
        captured["arguments"] = arguments
        return Handler()

    monkeypatch.setattr(image_provider.fal_client, "submit_async", fake_submit_async, raising=False)

    image_url = asyncio.run(
        image_provider._submit_real(
            "photorealistic adult woman portrait",
            "nudity, nsfw, penis",
            allow_nsfw=False,
            nsfw_level=0,
        )
    )

    assert image_url == "https://example.test/avatar.png"
    assert captured["model_id"] == "fal-ai/z-image/turbo"
    assert captured["arguments"]["enable_safety_checker"] is True
    assert captured["arguments"]["image_size"] == {"width": 1024, "height": 1024}
    assert captured["arguments"]["prompt"] == "photorealistic adult woman portrait"
    assert "nudity" not in captured["arguments"]["prompt"]
    assert "nsfw" not in captured["arguments"]["prompt"]
    assert "penis" not in captured["arguments"]["prompt"]


def test_submit_real_nsfw_allowed_still_sends_positive_only_prompt(monkeypatch):
    captured = {}

    class Handler:
        async def get(self):
            return {"images": [{"url": "https://example.test/photo.png"}]}

    async def fake_submit_async(model_id, arguments):
        captured["model_id"] = model_id
        captured["arguments"] = arguments
        return Handler()

    monkeypatch.setattr(image_provider.fal_client, "submit_async", fake_submit_async, raising=False)

    image_url = asyncio.run(
        image_provider._submit_real(
            "photorealistic adult woman portrait",
            "male, penis, testicles, bulge",
            allow_nsfw=True,
            nsfw_level=1,
        )
    )

    assert image_url == "https://example.test/photo.png"
    assert captured["model_id"] == "fal-ai/z-image/turbo"
    assert captured["arguments"]["enable_safety_checker"] is False
    assert captured["arguments"]["prompt"] == "photorealistic adult woman portrait"
    assert "Do not depict" not in captured["arguments"]["prompt"]
    assert "penis" not in captured["arguments"]["prompt"]
    assert "testicles" not in captured["arguments"]["prompt"]
    assert "bulge" not in captured["arguments"]["prompt"]


def test_submit_real_includes_fal_response_body_in_error(monkeypatch):
    class Handler:
        async def get(self):
            request = httpx.Request("POST", "https://queue.fal.run/fal-ai/z-image/requests/test")
            response = httpx.Response(
                422,
                request=request,
                text='{"detail":"prompt contains blocked safety terms"}',
            )
            raise httpx.HTTPStatusError("unprocessable", request=request, response=response)

    async def fake_submit_async(model_id, arguments):
        return Handler()

    monkeypatch.setattr(image_provider.fal_client, "submit_async", fake_submit_async, raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            image_provider._submit_real(
                "photorealistic adult woman portrait",
                "nudity, nsfw, penis",
                allow_nsfw=False,
                nsfw_level=0,
            )
        )

    assert "FAL request failed (422)" in str(exc_info.value)
    assert "prompt contains blocked safety terms" in str(exc_info.value)
