import logging

import replicate
import fal_client

logger = logging.getLogger(__name__)

# CLIP text encoder limit: 77 tokens. We use 75 words as conservative proxy.
_CLIP_MAX_WORDS = 75


def _truncate_for_clip(prompt: str, max_words: int = _CLIP_MAX_WORDS) -> str:
    """Truncate prompt to fit within CLIP token limit (77 tokens).

    Splits by comma, keeps tags from the beginning (highest priority:
    gender, appearance) and drops from the end (lowest priority:
    scene_details, style).
    """
    parts = [p.strip() for p in prompt.split(",") if p.strip()]
    result = []
    word_count = 0
    for part in parts:
        part_words = len(part.split())
        if word_count + part_words > max_words:
            break
        result.append(part)
        word_count += part_words
    truncated = ", ".join(result) if result else prompt[:300]
    if len(result) < len(parts):
        logger.info(f"Prompt truncated from {len(parts)} to {len(result)} tags ({word_count} words)")
    return truncated


async def generate_image(
    model_type: str,
    positive_prompt: str,
    negative_prompt: str = "",
    allow_nsfw: bool = True,
    nsfw_level: int = 0,
    seed: int = -1,
) -> str | None:
    """Generate an image and return the provider URL (or None on failure)."""
    if model_type == "anime":
        return await _submit_anime(positive_prompt, negative_prompt, seed=seed)
    elif model_type == "real":
        return await _submit_real(positive_prompt, allow_nsfw, nsfw_level)
    else:
        logger.warning(f"Unsupported model_type: {model_type}")
        return None


async def _submit_anime(positive_prompt: str, negative_prompt: str, seed: int = -1) -> str | None:
    positive_prompt = _truncate_for_clip(positive_prompt)
    negative_prompt = _truncate_for_clip(negative_prompt)

    model_version = (
        "aisha-ai-official/wai-nsfw-illustrious-v12:"
        "0fc0fa9885b284901a6f9c0b4d67701fd7647d157b88371427d63f8089ce140e"
    )
    result = await replicate.async_run(
        model_version,
        input={
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "vae": "default",
            "seed": seed,
            "cfg_scale": 5,
            "pag_scale": 5,
            "scheduler": "Euler a",
            "prepend_preprompt": False,
        },
    )
    if result and len(result) > 0 and hasattr(result[0], "url"):
        return result[0].url
    return None


async def _submit_real(prompt: str, allow_nsfw: bool, nsfw_level: int = 0) -> str | None:
    # Note: fal-ai/z-image/turbo is FLUX-based and does NOT support negative_prompt.
    handler = await fal_client.submit_async(
        "fal-ai/z-image/turbo",
        arguments={
            "prompt": prompt,
            "enable_safety_checker": not allow_nsfw,
            "image_size": {"width": 1024, "height": 1024},
        },
    )
    result = await handler.get()
    logger.info(f"FAL result (nsfw_level={nsfw_level}): {result}")

    if result and "images" in result and result["images"]:
        return result["images"][0]["url"]
    return None
