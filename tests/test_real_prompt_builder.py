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

from backend.api.image_gen.schemas.generate import ModelType, Prompt


def _real_character(character_id: str) -> dict:
    return {
        "id": character_id,
        "name": "Elena",
        "model_type": "real",
        "appearance": "solo, 1girl, russian woman, blonde hair, blue eyes",
        "visual": {
            "gender": "female",
            "nationality": "russian",
            "hair_color": "blonde",
            "eye_color": "blue",
            "body_type": "fit body",
            "boobs": "beautiful breasts",
            "wardrobe": {"nude": "nothing, showing her naked body"},
        },
    }


def test_real_female_prompt_gets_real_anatomy_and_identity_guards():
    prompt = Prompt.from_character(_real_character("elena_real"), outfit_key="nude", nsfw_level=4)

    positive, negative = asyncio.run(prompt.build_prompt(ModelType.real, gender="female"))

    assert prompt.character_base.startswith("single adult woman, anatomically female")
    assert "1girl" not in prompt.character_base
    assert "distinct individual face" in prompt.character_base
    assert "photorealistic adult woman" in positive
    assert "smooth firm skin" not in positive
    assert "slim waist" not in positive
    assert "attractive hips" not in positive
    assert "anatomically female nude body" in positive
    assert "penis" in negative
    assert "cellulite" in negative


def test_real_signature_varies_same_nationality_characters():
    first = Prompt.from_character(_real_character("same_nationality_a"), nsfw_level=4)
    second = Prompt.from_character(_real_character("same_nationality_b"), nsfw_level=4)

    assert first.character_base != second.character_base
    assert "individualized russian facial features" in first.character_base
    assert "individualized russian facial features" in second.character_base


def test_real_sfw_prompt_uses_character_body_without_auto_glamour_tags():
    character = {
        "id": "berta_like",
        "name": "Берта",
        "model_type": "real",
        "visual": {
            "gender": "female",
            "appearance": (
                "1girl, 25 years old, short black hair, piecey fringe falling above eyebrows, "
                "grey eyes, pale skin, small silver nose ring on left side"
            ),
            "body": "lean build",
            "face": "sharp features, big lips",
            "default_outfit": "crisp black button up shirt with rolled sleeves",
            "style_tags": "soft natural lighting, film photography, warm tones",
        },
    }
    prompt = Prompt.from_character(character, nsfw_level=0)
    prompt.facial_expression = "smirking, confident, alluring"

    positive, _ = asyncio.run(prompt.build_prompt(ModelType.real, gender="female"))

    assert positive.startswith("photorealistic adult woman, single subject")
    assert "lean build" in positive
    assert "slim hourglass figure" not in positive
    assert "toned athletic curves" not in positive
    assert "alluring" not in positive
    assert "smirking" in positive
    assert "confident" in positive


def test_anime_prompt_does_not_receive_real_layers():
    character = {
        "id": "anime_a",
        "name": "Aiko",
        "model_type": "anime",
        "appearance": "solo, 1girl, anime girl, blue hair",
        "visual": {"gender": "female"},
    }
    prompt = Prompt.from_character(character, nsfw_level=0)

    positive, _ = asyncio.run(prompt.build_prompt(ModelType.anime, gender="female"))

    assert "anime style" in positive
    assert "photorealistic adult woman" not in positive
    assert "distinct individual face" not in positive
