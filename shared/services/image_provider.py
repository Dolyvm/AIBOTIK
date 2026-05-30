import logging
import asyncio
import base64
from typing import Any

import replicate
import fal_client
import httpx

from shared.config import (
    REPLICATE_API_TOKEN,
    REPLICATE_REAL_GUIDANCE_SCALE,
    REPLICATE_REAL_HEIGHT,
    REPLICATE_REAL_MODEL,
    REPLICATE_REAL_NUM_INFERENCE_STEPS,
    REPLICATE_REAL_POLL_INTERVAL_SECONDS,
    REPLICATE_REAL_TIMEOUT_SECONDS,
    REPLICATE_REAL_WIDTH,
    RUNPOD_API_KEY,
    RUNPOD_MANHWA_ENDPOINT_ID,
    RUNPOD_MANHWA_POLL_INTERVAL_SECONDS,
    RUNPOD_MANHWA_TIMEOUT_SECONDS,
)
from shared.services.workflows.manhwa_illustrious import build_manhwa_workflow

logger = logging.getLogger(__name__)

# CLIP text encoder limit: 77 tokens. We use 75 words as conservative proxy.
_CLIP_MAX_WORDS = 75
_REPLICATE_API_BASE = "https://api.replicate.com/v1"


class ImageProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "image_provider_error",
        provider: str | None = None,
        user_message: str | None = None,
        retryable: bool = True,
    ):
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.user_message = user_message or message
        self.retryable = retryable

    def to_task_payload(self) -> dict[str, Any]:
        return {
            "error": self.user_message,
            "code": self.code,
            "provider": self.provider,
            "retryable": self.retryable,
        }


class ImageProviderGenerationError(ImageProviderError):
    def __init__(self, message: str, *, provider: str | None = None):
        super().__init__(
            message,
            code="image_provider_generation_failed",
            provider=provider,
            user_message="Не удалось создать real фото через Replicate",
            retryable=True,
        )


def _truncate_for_clip(prompt: str, max_words: int = _CLIP_MAX_WORDS) -> str:
    """Truncate prompt to fit within CLIP token limit (77 tokens).

    Splits by comma, keeps tags from the beginning (highest priority after
    prompt compaction), and drops from the end.
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
        return await _submit_real_replicate(positive_prompt, negative_prompt, nsfw_level, seed=seed)
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


def _extract_replicate_image(output: Any) -> str | None:
    """Normalize common Replicate image output shapes to a URL/data URL."""
    if isinstance(output, str):
        return _as_data_url(output)

    url_attr = getattr(output, "url", None)
    if url_attr:
        try:
            value = url_attr() if callable(url_attr) else url_attr
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return value

    if isinstance(output, (list, tuple)):
        for item in output:
            found = _extract_replicate_image(item)
            if found:
                return found
        return None

    if isinstance(output, dict):
        for key in ("url", "image_url", "uri"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("images", "files", "output"):
            found = _extract_replicate_image(output.get(key))
            if found:
                return found

    return None


def _real_replicate_input(prompt: str, negative_prompt: str, seed: int = -1) -> dict[str, Any]:
    payload = {
        "prompt": prompt,
        "width": REPLICATE_REAL_WIDTH,
        "height": REPLICATE_REAL_HEIGHT,
        "num_inference_steps": REPLICATE_REAL_NUM_INFERENCE_STEPS,
        "guidance_scale": REPLICATE_REAL_GUIDANCE_SCALE,
    }
    if seed != -1:
        payload["seed"] = seed
    return payload


def _replicate_headers() -> dict[str, str]:
    if not REPLICATE_API_TOKEN:
        raise ImageProviderGenerationError("REPLICATE_API_TOKEN is not configured", provider="replicate")
    return {
        "Authorization": f"Token {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _replicate_version(model_id: str) -> str:
    if ":" not in model_id:
        raise ImageProviderGenerationError("Replicate model version is missing", provider="replicate")
    return model_id.rsplit(":", 1)[1]


def _replicate_prediction_request(model_id: str, input_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if ":" in model_id:
        return f"{_REPLICATE_API_BASE}/predictions", {
            "version": _replicate_version(model_id),
            "input": input_payload,
        }
    if model_id.count("/") == 1:
        owner, name = model_id.split("/", 1)
        return f"{_REPLICATE_API_BASE}/models/{owner}/{name}/predictions", {
            "input": input_payload,
        }
    raise ImageProviderGenerationError("Invalid Replicate model identifier", provider="replicate")


async def _cancel_replicate_prediction(
    client: httpx.AsyncClient,
    prediction: dict[str, Any],
    headers: dict[str, str],
) -> None:
    prediction_id = prediction.get("id")
    cancel_url = (prediction.get("urls") or {}).get("cancel")
    if not cancel_url and prediction_id:
        cancel_url = f"{_REPLICATE_API_BASE}/predictions/{prediction_id}/cancel"
    if not cancel_url:
        return
    try:
        await client.post(cancel_url, headers=headers)
    except Exception:
        logger.warning("Failed to cancel Replicate prediction: id=%s", prediction_id, exc_info=True)


async def _run_replicate_prediction(model_id: str, input_payload: dict[str, Any]) -> Any:
    headers = _replicate_headers()
    timeout = max(1, REPLICATE_REAL_TIMEOUT_SECONDS)
    poll_interval = max(0.5, REPLICATE_REAL_POLL_INTERVAL_SECONDS)
    request_timeout = httpx.Timeout(30.0, connect=10.0)
    deadline = asyncio.get_running_loop().time() + timeout

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        prediction_url, prediction_body = _replicate_prediction_request(model_id, input_payload)
        response = await client.post(
            prediction_url,
            headers=headers,
            json=prediction_body,
        )
        response.raise_for_status()
        prediction = response.json()
        prediction_id = prediction.get("id")
        get_url = (prediction.get("urls") or {}).get("get") or f"{_REPLICATE_API_BASE}/predictions/{prediction_id}"
        last_status = prediction.get("status")
        logger.info(
            "Replicate real prediction created: model=%s prediction_id=%s status=%s timeout=%ss",
            model_id,
            prediction_id,
            last_status,
            timeout,
        )

        while True:
            status = prediction.get("status")
            if status == "succeeded":
                return prediction.get("output")
            if status in {"failed", "canceled"}:
                logger.error(
                    "Replicate real prediction ended without image: model=%s prediction_id=%s status=%s",
                    model_id,
                    prediction_id,
                    status,
                )
                raise ImageProviderGenerationError("Replicate real image prediction failed", provider="replicate")

            if asyncio.get_running_loop().time() >= deadline:
                await _cancel_replicate_prediction(client, prediction, headers)
                logger.error(
                    "Replicate real prediction timed out: model=%s prediction_id=%s status=%s timeout=%ss",
                    model_id,
                    prediction_id,
                    status,
                    timeout,
                )
                raise ImageProviderGenerationError("Replicate real image prediction timed out", provider="replicate")

            if status != last_status:
                logger.info(
                    "Replicate real prediction status: model=%s prediction_id=%s status=%s",
                    model_id,
                    prediction_id,
                    status,
                )
                last_status = status

            await asyncio.sleep(poll_interval)
            response = await client.get(get_url, headers=headers)
            response.raise_for_status()
            prediction = response.json()


async def _submit_real_replicate(
    prompt: str,
    negative_prompt: str,
    nsfw_level: int = 0,
    seed: int = -1,
) -> str | None:
    input_payload = _real_replicate_input(prompt, negative_prompt, seed=seed)
    try:
        logger.info(
            "Submitting Replicate real image: model=%s prompt_chars=%s negative_chars=%s nsfw_level=%s seed=%s",
            REPLICATE_REAL_MODEL,
            len(prompt or ""),
            len(negative_prompt or ""),
            nsfw_level,
            input_payload.get("seed", "random"),
        )
        result = await _run_replicate_prediction(REPLICATE_REAL_MODEL, input_payload)
    except ImageProviderError:
        raise
    except Exception as e:
        logger.error(
            "Replicate real image request failed: model=%s prompt_chars=%s negative_chars=%s nsfw_level=%s error_type=%s",
            REPLICATE_REAL_MODEL,
            len(prompt or ""),
            len(negative_prompt or ""),
            nsfw_level,
            type(e).__name__,
        )
        raise ImageProviderGenerationError("Replicate real image request failed", provider="replicate") from e

    image_url = _extract_replicate_image(result)
    logger.info(
        "Replicate real image result: model=%s nsfw_level=%s has_image=%s",
        REPLICATE_REAL_MODEL,
        nsfw_level,
        bool(image_url),
    )
    return image_url


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
        logger.info(
            "Submitting FAL real image: prompt_chars=%s negative_chars=%s allow_nsfw=%s nsfw_level=%s",
            len(prompt or ""),
            len(negative_prompt or ""),
            allow_nsfw,
            nsfw_level,
        )
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
    except Exception:
        logger.exception(
            "FAL real image request failed: prompt_chars=%s negative_chars=%s allow_nsfw=%s nsfw_level=%s",
            len(prompt or ""),
            len(negative_prompt or ""),
            allow_nsfw,
            nsfw_level,
        )
        raise

    logger.info(f"FAL result (nsfw_level={nsfw_level}): {result}")
    if isinstance(result, dict):
        image_meta = result["images"][0] if result.get("images") else {}
        image_meta = image_meta if isinstance(image_meta, dict) else {}
        logger.info(
            "FAL real image metadata: has_nsfw_concepts=%s seed=%s prompt_chars=%s",
            result.get("has_nsfw_concepts", image_meta.get("has_nsfw_concepts")),
            result.get("seed"),
            len(str(result.get("prompt") or "")),
        )

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
