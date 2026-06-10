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

from backend.api.image_gen.services.scene_analyzer import (
    SceneAnalysis,
    analyze_visual_context,
    apply_visual_safety_policy,
    has_explicit_nude_or_sex_context,
    infer_nsfw_level_from_history,
)


def _history(text: str) -> list[dict]:
    return [{"role": "assistant", "content": text}]


def test_visual_context_ignores_prod_false_positive_substrings():
    text = (
        "Кончики его ушей покраснели. Он закончил с предыдущим образцом, "
        "застегнул страховку и улыбнулся, обнажая острые зубы."
    )

    history = _history(text)
    context = analyze_visual_context(history)

    assert context.level == 0
    assert context.trigger_type == "none"
    assert has_explicit_nude_or_sex_context(history) is False
    assert infer_nsfw_level_from_history(
        history,
        heat_level=1,
        arousal=10,
        allow_nsfw=True,
    ) == 1


def test_visual_context_distinguishes_clothed_sensual_from_nude():
    history = _history("Она в белье сидит на кровати и смотрит с явным желанием.")

    context = analyze_visual_context(history)

    assert context.level == 2
    assert context.explicit_nude_or_sex is False
    assert infer_nsfw_level_from_history(history, heat_level=3, arousal=70) == 2


def test_visual_context_allows_nude_only_for_explicit_visual_terms():
    history = _history("Она медленно раздевается и остается полностью без одежды.")

    context = analyze_visual_context(history)

    assert context.level == 4
    assert context.explicit_nude_or_sex is True
    assert infer_nsfw_level_from_history(history, heat_level=1, arousal=10) == 4


def test_visual_safety_clamps_early_nude_scene_to_default_outfit():
    scene = SceneAnalysis(
        location="classroom after school",
        pose="standing nervously near desk",
        outfit_key="nude",
        emotion="nervous, shy, blushing",
        nsfw_level=4,
    )

    safe_scene, context = apply_visual_safety_policy(
        scene,
        _history("Кончики его ушей покраснели, он стоял у парты и смущался."),
        {"default_outfit": "school uniform", "nude": "nothing"},
        allow_nsfw=True,
        requested_outfit="default_outfit",
        heat_level=1,
        arousal=10,
        mood="neutral",
    )

    assert context.level == 0
    assert safe_scene.nsfw_level == 1
    assert safe_scene.outfit_key == "default_outfit"


def test_visual_safety_preserves_explicit_nude_scene():
    scene = SceneAnalysis(
        location="bedroom night",
        pose="standing close",
        outfit_key="default_outfit",
        emotion="aroused",
        nsfw_level=4,
    )

    safe_scene, context = apply_visual_safety_policy(
        scene,
        _history("Она раздевается и остается полностью голая перед зеркалом."),
        {"default_outfit": "dress", "nude": "nothing"},
        allow_nsfw=True,
        requested_outfit="default_outfit",
        heat_level=1,
        arousal=10,
        mood="neutral",
    )

    assert context.level == 4
    assert safe_scene.nsfw_level == 4
    assert safe_scene.outfit_key == "nude"


def test_visual_safety_respects_explicit_requested_nude_outfit():
    scene = SceneAnalysis(
        location="studio",
        pose="standing",
        outfit_key="nude",
        nsfw_level=1,
    )

    safe_scene, context = apply_visual_safety_policy(
        scene,
        _history("Она спокойно позирует в студии."),
        {"default_outfit": "dress", "nude": "nothing"},
        allow_nsfw=True,
        requested_outfit="nude",
        heat_level=0,
        arousal=0,
        mood="neutral",
    )

    assert context.level == 0
    assert safe_scene.nsfw_level == 4
    assert safe_scene.outfit_key == "nude"
