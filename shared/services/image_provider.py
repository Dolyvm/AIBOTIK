import logging

import replicate
import fal_client

logger = logging.getLogger(__name__)


async def generate_image(
    model_type: str,
    positive_prompt: str,
    negative_prompt: str = "",
    allow_nsfw: bool = True,
    nsfw_level: int = 0,
) -> str | None:
    """Generate an image and return the provider URL (or None on failure)."""
    if model_type == "anime":
        return await _submit_anime(positive_prompt, negative_prompt)
    elif model_type == "real":
        return await _submit_real(positive_prompt, allow_nsfw, nsfw_level)
    else:
        logger.warning(f"Unsupported model_type: {model_type}")
        return None


async def _submit_anime(positive_prompt: str, negative_prompt: str) -> str | None:
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
            "seed": -1,
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
