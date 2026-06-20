import asyncio
import json
import os
import sys
import types
from pathlib import Path

import pytest

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

from scripts.init_prompts import PROMPT_METADATA
from shared.database.repositories.subscription import SubscriptionRepository
from shared.models import SubscriptionPlan
from shared.services import photo_generation as photo
from shared.services.prompt_service import (
    DEFAULT_PROMPTS,
    PHOTO_PROMPT_KEYS as DEFAULT_PHOTO_PROMPT_KEYS,
)
from shared.services.workflows.manhwa_illustrious import MANHWA_BASE_NEGATIVE, MANHWA_BASE_POSITIVE
from shared.subscription_plans import PLAN_LIMITS, USAGE_TYPE_MAP


PHOTO_PROMPT_KEYS = DEFAULT_PHOTO_PROMPT_KEYS


def _fake_prompt_lookup(overrides: dict[str, str]):
    async def fake_get_prompt(key):
        return overrides.get(key, DEFAULT_PROMPTS[key])

    return fake_get_prompt


class FakeLLM:
    def __init__(self):
        self.payload = None

    async def generate(self, **kwargs):
        self.payload = json.loads(kwargs["messages"][0]["content"])
        return types.SimpleNamespace(
            content=json.dumps(
                {
                    "pose": "standing",
                    "expression": "soft smile",
                    "emotion": "playful",
                    "clothing": "black dress",
                    "wardrobe_key": "",
                    "setting": "bedroom",
                    "scene_notes": "warm light",
                    "nsfw_level": 2,
                }
            )
        )


def test_photo_scene_extractor_uses_only_last_five_messages(monkeypatch):
    async def fake_get_prompt(key):
        assert key == "photo_scene_extractor_real"
        return "extract"

    monkeypatch.setattr(photo, "get_prompt", fake_get_prompt)
    llm = FakeLLM()
    service = photo.PhotoGenerationService(llm_client=llm, replicate_client=object())
    messages = [{"role": "user", "content": f"message {i}"} for i in range(7)]

    scene = asyncio.run(
        service.build_scene(
            {
                "id": "char",
                "name": "Char",
                "model_type": "real",
                "is_nsfw": True,
                "visual": {"gender": "female"},
            },
            messages,
        )
    )

    assert [m["content"] for m in llm.payload["recent_messages"]] == [
        "message 2",
        "message 3",
        "message 4",
        "message 5",
        "message 6",
    ]
    assert scene["clothing"] == "black dress"
    assert "nsfw_level" not in scene


def test_real_payload_has_no_negative_prompt(monkeypatch):
    monkeypatch.setattr(
        photo,
        "get_prompt",
        _fake_prompt_lookup(
            {
                "photo_prompt_real_female": (
                    "{appearance}, {body}, {face}, {clothing}, {pose}, {expression}, {setting}"
                )
            }
        ),
    )
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    bundle = asyncio.run(
        service.build_prompt_bundle(
            {
                "name": "Emily",
                "model_type": "real",
                "appearance": "blonde hair",
                "visual": {
                    "gender": "female",
                    "body": "fit body",
                    "face": "blue eyes",
                    "default_outfit": "red dress",
                },
            },
            {"pose": "sitting", "expression": "smiling", "setting": "studio"},
        )
    )

    assert bundle.replicate_model == photo.REAL_MODEL
    assert bundle.negative_prompt is None
    assert "negative_prompt" not in bundle.replicate_input
    assert bundle.replicate_input["width"] == 1024
    assert bundle.replicate_input["height"] == 1024
    assert bundle.replicate_input["num_inference_steps"] == 9
    assert bundle.replicate_input["guidance_scale"] == 0.0


def test_real_missing_default_outfit_uses_safe_wardrobe_fallback(monkeypatch):
    monkeypatch.setattr(
        photo,
        "get_prompt",
        _fake_prompt_lookup({"photo_prompt_real_female": "{clothing}, {pose}, {body}"}),
    )
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    bundle = asyncio.run(
        service.build_prompt_bundle(
            {
                "name": "Emily",
                "model_type": "real",
                "visual": {
                    "gender": "female",
                    "body": "fit body, beautiful breasts",
                    "wardrobe": {
                        "casual": "designer jeans, fitted white sweater",
                        "nude": "nothing, showing her naked body",
                    },
                },
            },
            {"pose": "sitting at a hotel bar", "outfit_action": "none"},
        )
    )

    assert "fully clothed, designer jeans, fitted white sweater" in bundle.prompt
    assert "naked body" not in bundle.prompt
    assert bundle.state_meta_update == {
        "photo_outfit": {
            "source": "default",
            "wardrobe_key": "",
            "clothing": "designer jeans, fitted white sweater",
        }
    }


def test_anime_missing_default_outfit_does_not_use_real_fallback(monkeypatch):
    monkeypatch.setattr(
        photo,
        "get_prompt",
        _fake_prompt_lookup(
            {
                "photo_prompt_anime_female": "{clothing}, {pose}",
                "photo_negative_anime_female": "bad anatomy",
            }
        ),
    )
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    bundle = asyncio.run(
        service.build_prompt_bundle(
            {
                "name": "Aiko",
                "model_type": "anime",
                "visual": {
                    "gender": "female",
                    "wardrobe": {
                        "casual": "school uniform",
                        "nude": "nothing, showing her naked body",
                    },
                },
            },
            {"pose": "standing", "outfit_action": "none"},
        )
    )

    assert bundle.prompt == "standing"
    assert "fully clothed" not in bundle.prompt
    assert "casual modern outfit" not in bundle.prompt
    assert "school uniform" not in bundle.prompt


def test_visual_data_character_shape_is_supported(monkeypatch):
    monkeypatch.setattr(
        photo,
        "get_prompt",
        _fake_prompt_lookup({"photo_prompt_real_male": "{appearance}, {body}, {face}, {clothing}"}),
    )
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    bundle = asyncio.run(
        service.build_prompt_bundle(
            {
                "name": "Alex",
                "visual_data": {
                    "model_type": "real",
                    "gender": "male",
                    "appearance": "dark hair",
                    "body": "broad shoulders",
                    "face": "strong jaw",
                    "default_outfit": "white shirt",
                },
            },
            {},
        )
    )

    assert bundle.model_type == "real"
    assert bundle.gender == "male"
    assert "dark hair" in bundle.prompt
    assert "white shirt" in bundle.prompt


def test_anime_payload_uses_gender_specific_negative_prompt(monkeypatch):
    monkeypatch.setattr(
        photo,
        "get_prompt",
        _fake_prompt_lookup(
            {
                "photo_prompt_anime_male": "1boy,  man, anime illustration, {clothing}, {appearance}",
                "photo_negative_anime_male": "woman, girl, multiple people",
            }
        ),
    )
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    bundle = asyncio.run(
        service.build_prompt_bundle(
            {
                "name": "Alex",
                "model_type": "anime",
                "appearance": "black hair",
                "visual": {
                    "gender": "male",
                    "wardrobe": {"gym": "boxing shorts"},
                    "default_outfit": "black shirt",
                },
            },
            {"wardrobe_key": "gym"},
        )
    )

    assert bundle.replicate_model == photo.ANIME_MODEL_VERSION
    assert bundle.negative_prompt == "woman, girl, multiple people"
    assert bundle.replicate_input["negative_prompt"] == "woman, girl, multiple people"
    assert bundle.replicate_input["cfg_scale"] == 5
    assert bundle.replicate_input["pag_scale"] == 5
    assert bundle.replicate_input["scheduler"] == "Euler a"
    assert bundle.replicate_input["vae"] == "default"
    assert "boxing shorts" in bundle.prompt


def test_visual_parts_preserve_subject_tags_and_dedupe_across_groups(monkeypatch):
    monkeypatch.setattr(photo, "get_prompt", _fake_prompt_lookup({}))
    policy = asyncio.run(photo.get_photo_prompt_policy())

    parts = photo._visual_parts(
        {
            "appearance": "solo, 1girl, anime girl, bob haircut, brown hair, small breasts",
            "visual": {
                "gender": "female",
                "body_type": "petite figure",
                "boobs": "small breasts",
                "hair_color": "brown",
                "haircut": "bob haircut",
                "eye_color": "green",
                "skin": "clear",
                "style_tags": "small breasts, cinematic, green eyes",
            },
        },
        policy,
    )

    assert parts["appearance"] == "solo, 1girl, anime girl, bob haircut, brown hair, small breasts"
    assert parts["body"] == "petite figure, small breasts"
    assert parts["face"] == "brown hair, bob haircut, green eyes, clear skin"
    assert parts["style_tags"] == "small breasts, cinematic, green eyes"


def test_template_rendering_cleans_empty_and_duplicate_comma_tags():
    assert photo._render_template("alpha, {missing}, beta, , alpha", {}) == "alpha, beta"


def test_replicate_client_resolves_owner_model_to_latest_version():
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"latest_version": {"id": "a" * 64}}

    class FakeHTTPClient:
        def __init__(self):
            self.calls = []

        async def get(self, url, headers):
            self.calls.append((url, headers))
            return FakeResponse()

    http_client = FakeHTTPClient()
    client = photo.ReplicateImageClient(api_token="token")

    version = asyncio.run(
        client._resolve_version(
            http_client,
            "prunaai/z-image-turbo",
            {"Authorization": "Bearer token"},
        )
    )
    cached = asyncio.run(
        client._resolve_version(
            http_client,
            "prunaai/z-image-turbo",
            {"Authorization": "Bearer token"},
        )
    )

    assert version == "a" * 64
    assert cached == "a" * 64
    assert len(http_client.calls) == 1


def test_anime_model_uses_wai_nsfw_illustrious_v12_pinned_version():
    assert (
        photo.ANIME_MODEL_VERSION
        == "aisha-ai-official/wai-nsfw-illustrious-v12:"
        "0fc0fa9885b284901a6f9c0b4d67701fd7647d157b88371427d63f8089ce140e"
    )


def test_replicate_client_uses_version_hash_from_owner_model_version():
    client = photo.ReplicateImageClient(api_token="token")

    version = asyncio.run(
        client._resolve_version(
            object(),
            photo.ANIME_MODEL_VERSION,
            {"Authorization": "Bearer token"},
        )
    )

    assert version == photo.ANIME_MODEL_VERSION.rsplit(":", 1)[1]


def test_manhwa_uses_runpod_provider_and_manhwa_prompts(monkeypatch):
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    bundle = asyncio.run(
        service.build_prompt_bundle(
            {
                "name": "M",
                "model_type": "manhwa",
                "visual": {"gender": "male", "appearance": "black hair"},
            },
            {"primary_pose": "standing", "composition": "full body"},
        )
    )

    assert bundle.provider == "runpod_manhwa"
    assert bundle.replicate_model == "runpod:manhwa"
    assert bundle.prompt_metadata["model_type"] == "manhwa"
    assert "manhwa style" in bundle.prompt
    assert bundle.prompt_metadata["provider_prompt"].startswith(MANHWA_BASE_POSITIVE)
    assert bundle.prompt_metadata["provider_negative_prompt"].startswith(MANHWA_BASE_NEGATIVE)
    assert bundle.prompt_metadata["provider_prompt"] != bundle.prompt
    assert bundle.prompt_metadata["provider_negative_prompt"] != bundle.negative_prompt


def test_photo_prompts_are_registered_for_admin_and_defaults():
    assert PHOTO_PROMPT_KEYS == DEFAULT_PHOTO_PROMPT_KEYS
    assert PHOTO_PROMPT_KEYS <= set(DEFAULT_PROMPTS)
    assert PHOTO_PROMPT_KEYS <= set(PROMPT_METADATA)
    assert {PROMPT_METADATA[key]["category"] for key in PHOTO_PROMPT_KEYS} == {
        "photo",
        "photo_policy",
    }
    assert all("nsfw_level" not in DEFAULT_PROMPTS[key] for key in PHOTO_PROMPT_KEYS)


@pytest.mark.parametrize(
    ("gender", "subject_tag", "identity_tag", "body_tag", "clothing_tag", "setting_tag"),
    [
        ("female", "1girl", "blonde hair", "medium breasts", "bunny cosplay", "cafe"),
        ("male", "1boy", "black hair", "athletic build", "black shirt", "street"),
    ],
)
def test_default_anime_prompts_are_short_tag_prompts(
    monkeypatch,
    gender,
    subject_tag,
    identity_tag,
    body_tag,
    clothing_tag,
    setting_tag,
):
    async def fake_get_prompt(key):
        return DEFAULT_PROMPTS[key]

    monkeypatch.setattr(photo, "get_prompt", fake_get_prompt)
    service = photo.PhotoGenerationService(llm_client=object(), replicate_client=object())

    character = {
        "name": "Aiko" if gender == "female" else "Ren",
        "model_type": "anime",
        "appearance": (
            "solo, 1girl, waifu, gorgeous beauty, long blonde hair, blue eyes, soft blush"
            if gender == "female"
            else "solo, 1boy, handsome man, short black hair, gray eyes, sharp gaze"
        ),
        "visual": {
            "gender": gender,
            "body_type": "curvy figure" if gender == "female" else "athletic build",
            "boobs": "medium breasts" if gender == "female" else "",
            "hair_color": "blonde" if gender == "female" else "black",
            "haircut": "long wavy hair" if gender == "female" else "short messy hair",
            "eye_color": "blue" if gender == "female" else "gray",
            "default_outfit": (
                "bunny cosplay, waitress outfit, white cuffs, black bodice, red bow tie, long stockings"
                if gender == "female"
                else "black shirt, casual jacket, dark jeans, silver chain"
            ),
            "style_tags": "high quality, detailed face, cinematic lighting, ultra detailed",
        },
    }
    scene = {
        "pose": "leaning over counter, hands on table, looking at viewer, seductive posture",
        "expression": "seductive smile, blushing cheeks, half-lidded eyes",
        "setting": (
            "cafe, wooden counter, coffee cups, menu board"
            if gender == "female"
            else "street, shop signs, narrow alley, afternoon light"
        ),
        "scene_notes": "upper body, warm sunlight, dynamic angle, detailed props",
    }

    bundle = asyncio.run(service.build_prompt_bundle(character, scene))

    assert photo._estimate_prompt_tokens(bundle.prompt) <= photo.PROMPT_BUDGETS["anime"]
    assert photo._estimate_prompt_tokens(bundle.negative_prompt or "") <= photo.ANIME_NEGATIVE_BUDGET
    assert subject_tag in bundle.prompt
    assert "" in bundle.prompt
    assert identity_tag in bundle.prompt
    assert body_tag in bundle.prompt
    assert clothing_tag in bundle.prompt
    assert setting_tag in bundle.prompt
    assert "leaning over counter" in bundle.prompt

    prompt_lower = bundle.prompt.lower()
    for banned in ("anime illustration", "detailed face", "high quality", "masterpiece"):
        assert banned not in prompt_lower


def test_images_generated_subscription_limits_are_registered():
    assert USAGE_TYPE_MAP["images_generated"] == "images_generated"
    assert "images_generated" in SubscriptionRepository.ALLOWED_FIELDS
    assert "bonus_images_generated" in SubscriptionRepository.ALLOWED_BONUS_FIELDS
    assert PLAN_LIMITS[SubscriptionPlan.FREE]["images_generated"] == 20
    assert PLAN_LIMITS[SubscriptionPlan.PLUS_WEEKLY]["images_generated"] == 100
    assert PLAN_LIMITS[SubscriptionPlan.PLUS_MONTHLY]["images_generated"] == 300
    assert PLAN_LIMITS[SubscriptionPlan.PRO]["images_generated"] == 9999
