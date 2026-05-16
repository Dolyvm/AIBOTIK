import logging
import asyncio
import base64
from typing import Any

import replicate
import fal_client
import httpx

from shared.config import (
    RUNPOD_API_KEY,
    RUNPOD_MANHWA_ENDPOINT_ID,
    RUNPOD_MANHWA_POLL_INTERVAL_SECONDS,
    RUNPOD_MANHWA_TIMEOUT_SECONDS,
)
from shared.services.workflows.manhwa_illustrious import build_manhwa_workflow

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
    elif model_type == "manhwa":
        return await _submit_manhwa(positive_prompt, negative_prompt, seed=seed)
    elif model_type == "real":
        return await _submit_real(positive_prompt, negative_prompt, allow_nsfw, nsfw_level)
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


_FAL_ERROR_BODY_LIMIT = 1000


def _compose_real_prompt(prompt: str, negative_prompt: str, allow_nsfw: bool) -> str:
    """Return the positive prompt for real models.

    fal-ai/z-image/turbo does not support native negative prompts. Folding explicit
    negative terms into the positive prompt triggers FAL content policy checks, so
    keep the request prompt positive-only.
    """
    return prompt


def _format_fal_http_error(error: httpx.HTTPStatusError) -> str:
    response = error.response
    status_code = response.status_code if response is not None else "unknown"
    body = ""
    if response is not None:
        try:
            body = response.text.strip()
        except Exception:
            body = ""
    if body:
        body = body[:_FAL_ERROR_BODY_LIMIT]
        return f"FAL request failed ({status_code}): {body}"
    return f"FAL request failed ({status_code}): {error}"


async def _submit_real(
    prompt: str,
    negative_prompt: str,
    allow_nsfw: bool,
    nsfw_level: int = 0,
) -> str | None:
    # Note: fal-ai/z-image/turbo is FLUX-based and does NOT support negative_prompt.
    prompt = _compose_real_prompt(prompt, negative_prompt, allow_nsfw)
    try:
        handler = await fal_client.submit_async(
            "fal-ai/z-image/turbo",
            arguments={
                "prompt": prompt,
                "enable_safety_checker": not allow_nsfw,
                "image_size": {"width": 1024, "height": 1024},
            },
        )
        result = await handler.get()
    except httpx.HTTPStatusError as e:
        error_msg = _format_fal_http_error(e)
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    logger.info(f"FAL result (nsfw_level={nsfw_level}): {result}")

    if result and "images" in result and result["images"]:
        return result["images"][0]["url"]
    return None


def _as_data_url(value: str, mime_type: str = "image/png") -> str | None:
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://") or value.startswith("data:image/"):
        return value
    value = "".join(value.split())
    try:
        base64.b64decode(value, validate=True)
    except Exception:
        return None
    return f"data:{mime_type};base64,{value}"


def _extract_runpod_image(output: Any) -> str | None:
    """Normalize common RunPod/ComfyUI output shapes to URL or data URL."""
    if isinstance(output, str):
        return _as_data_url(output)

    if isinstance(output, list):
        for item in output:
            found = _extract_runpod_image(item)
            if found:
                return found
        return None

    if not isinstance(output, dict):
        return None

    for key in ("url", "image_url", "uri"):
        value = output.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("base64", "image", "data", "b64_json"):
        value = output.get(key)
        if isinstance(value, str):
            mime_type = output.get("mime_type") or output.get("content_type") or "image/png"
            found = _as_data_url(value, mime_type)
            if found:
                return found

    for key in ("images", "files", "output"):
        found = _extract_runpod_image(output.get(key))
        if found:
            return found

    return None


async def _submit_manhwa(positive_prompt: str, negative_prompt: str, seed: int = -1) -> str | None:
    if not RUNPOD_API_KEY or not RUNPOD_MANHWA_ENDPOINT_ID:
        logger.error("RunPod manhwa provider is not configured")
        return None

    positive_prompt = _truncate_for_clip(positive_prompt, max_words=120)
    negative_prompt = _truncate_for_clip(negative_prompt, max_words=120)
    workflow = build_manhwa_workflow(positive_prompt, negative_prompt, seed=seed)

    base_url = f"https://api.runpod.ai/v2/{RUNPOD_MANHWA_ENDPOINT_ID}"
    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}"}
    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/run",
            headers=headers,
            json={
                "input": {
                    "workflow": workflow,
                    "prompt": workflow,
                    "return_base64": True,
                }
            },
        )
        response.raise_for_status()
        payload = response.json()

        job_id = payload.get("id") or payload.get("job_id")
        immediate = _extract_runpod_image(payload.get("output"))
        if immediate:
            return immediate
        if not job_id:
            logger.error(f"RunPod did not return job id: {payload}")
            return None

        deadline = asyncio.get_running_loop().time() + RUNPOD_MANHWA_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(RUNPOD_MANHWA_POLL_INTERVAL_SECONDS)
            status_response = await client.get(f"{base_url}/status/{job_id}", headers=headers)
            status_response.raise_for_status()
            status_payload = status_response.json()
            status = (status_payload.get("status") or "").upper()

            if status == "COMPLETED":
                image = _extract_runpod_image(status_payload.get("output"))
                if image:
                    return image
                logger.error(f"RunPod completed without image output: {status_payload}")
                return None

            if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                logger.error(f"RunPod job {job_id} failed: {status_payload}")
                return None

        logger.error(f"RunPod job {job_id} timed out after {RUNPOD_MANHWA_TIMEOUT_SECONDS}s")
        return None
