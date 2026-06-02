"""RunPod FaceFusion provider for final custom-photo face swap."""
import asyncio
import base64
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from shared.config import (
    RUNPOD_API_KEY,
    RUNPOD_FACEFUSION_ENDPOINT_ID,
    RUNPOD_FACEFUSION_EXECUTION_TIMEOUT_MS,
    RUNPOD_FACEFUSION_OUTPUT_FORMAT,
    RUNPOD_FACEFUSION_POLL_INTERVAL_SECONDS,
    RUNPOD_FACEFUSION_PRESET,
    RUNPOD_FACEFUSION_TIMEOUT_SECONDS,
    RUNPOD_FACEFUSION_TTL_MS,
)
from shared.services.image_provider import ImageProviderError
from shared.services.workflows.facefusion_comfy import (
    SOURCE_IMAGE_NAME,
    TARGET_IMAGE_NAME,
    build_facefusion_workflow,
)

logger = logging.getLogger(__name__)

_SENSITIVE_IMAGE_KEYS = {"image", "source_image", "target_image"}
_SENSITIVE_SECRET_KEYS = {"authorization", "api_key", "token", "key", "secret"}


def _facefusion_error(message: str, *, retryable: bool = True) -> ImageProviderError:
    return ImageProviderError(
        message,
        code="facefusion_swap_failed",
        provider="runpod_facefusion",
        user_message="Не удалось применить лицо к фото, попробуйте еще раз",
        retryable=retryable,
    )


def _headers() -> dict[str, str]:
    if not RUNPOD_API_KEY:
        raise _facefusion_error("RUNPOD_API_KEY/RUNPOD_KEY is not configured", retryable=False)
    return {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }


def _endpoint_url(path: str) -> str:
    if not RUNPOD_FACEFUSION_ENDPOINT_ID:
        raise _facefusion_error("RUNPOD_FACEFUSION_ENDPOINT_ID is not configured", retryable=False)
    return f"https://api.runpod.ai/v2/{RUNPOD_FACEFUSION_ENDPOINT_ID}{path}"


def _redact_image_value(value: str) -> str:
    if value.startswith("data:image/"):
        header = value.split(",", 1)[0]
        return f"<redacted data-url {header} chars={len(value)}>"
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"<redacted image-url scheme={parsed.scheme} host={parsed.netloc} chars={len(value)}>"
    return f"<redacted image-string chars={len(value)}>"


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


def _sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    if isinstance(key, str) and key.lower() in _SENSITIVE_SECRET_KEYS:
        return "<redacted secret>"

    if isinstance(value, str):
        if key in _SENSITIVE_IMAGE_KEYS or value.startswith("data:image/"):
            return _redact_image_value(value)
        if len(value) > 300:
            return f"{value[:300]}...<truncated chars={len(value)}>"
        return value

    if isinstance(value, dict):
        return {str(k): _sanitize_for_log(v, key=str(k)) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value[:20]]

    return value


def _output_image_present(data: dict[str, Any]) -> bool:
    output = data.get("output")
    if isinstance(output, dict):
        image = output.get("image")
        if isinstance(image, str) and bool(image):
            return True
        for item in output.get("images") or []:
            if isinstance(item, dict) and any(item.get(key) for key in ("data", "image", "url")):
                return True
        return False
    return isinstance(output, str) and output.startswith("data:image/")


def _runpod_status_summary(data: dict[str, Any]) -> dict[str, Any]:
    output = data.get("output")
    output_error = output.get("error") if isinstance(output, dict) else None
    return {
        "status": data.get("status"),
        "delayTime": data.get("delayTime"),
        "executionTime": data.get("executionTime"),
        "error": data.get("error") or output_error,
        "message": data.get("message"),
        "has_output_image": _output_image_present(data),
    }


def _log_runpod_status(job_id: str, data: dict[str, Any], *, prefix: str = "poll") -> None:
    summary = _runpod_status_summary(data)
    logger.info(
        "FaceFusion job %s: endpoint=%s id=%s status=%s delayTime=%s executionTime=%s "
        "has_output_image=%s error=%s message=%s",
        prefix,
        RUNPOD_FACEFUSION_ENDPOINT_ID,
        job_id,
        summary["status"],
        summary["delayTime"],
        summary["executionTime"],
        summary["has_output_image"],
        summary["error"],
        summary["message"],
    )


def _extract_output_image(data: dict[str, Any]) -> str | None:
    output = data.get("output")
    if isinstance(output, dict):
        image = output.get("image")
        if isinstance(image, str) and image:
            return image
        for item in output.get("images") or []:
            if not isinstance(item, dict):
                continue
            value = item.get("data") or item.get("image") or item.get("url")
            if isinstance(value, str) and value:
                image_type = item.get("type")
                if image_type == "s3_url" or value.startswith(("http://", "https://", "data:image/")):
                    return value
                mime_type = item.get("mime_type") or item.get("content_type") or "image/png"
                found = _as_data_url(value, mime_type)
                if found:
                    return found
        error = output.get("error")
        if error:
            raise _facefusion_error(str(error))
    if isinstance(output, str) and output.startswith("data:image/"):
        return output
    return None


async def _prepare_comfy_image(client: httpx.AsyncClient, image: str, name: str) -> dict[str, str]:
    if image.startswith("data:image/"):
        return {"name": name, "image": image}

    if image.startswith(("http://", "https://")):
        response = await client.get(image)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/png").split(";", 1)[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        encoded = base64.b64encode(response.content).decode("ascii")
        return {"name": name, "image": f"data:{content_type};base64,{encoded}"}

    found = _as_data_url(image)
    if found:
        return {"name": name, "image": found}

    raise _facefusion_error(f"Unsupported FaceFusion image input for {name}", retryable=False)


async def swap_face(source_image: str, target_image: str) -> str:
    """Run FaceFusion and return only output.image."""
    request_timeout = httpx.Timeout(30.0, connect=10.0)
    deadline = asyncio.get_running_loop().time() + max(1, RUNPOD_FACEFUSION_TIMEOUT_SECONDS)
    poll_interval = max(0.5, RUNPOD_FACEFUSION_POLL_INTERVAL_SECONDS)
    last_status_data: dict[str, Any] | None = None

    try:
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            workflow = build_facefusion_workflow(RUNPOD_FACEFUSION_PRESET, RUNPOD_FACEFUSION_OUTPUT_FORMAT)
            images = [
                await _prepare_comfy_image(client, source_image, SOURCE_IMAGE_NAME),
                await _prepare_comfy_image(client, target_image, TARGET_IMAGE_NAME),
            ]
            payload = {
                "input": {
                    "workflow": workflow,
                    "prompt": workflow,
                    "images": images,
                    "return_base64": True,
                },
                "policy": {
                    "executionTimeout": RUNPOD_FACEFUSION_EXECUTION_TIMEOUT_MS,
                    "ttl": RUNPOD_FACEFUSION_TTL_MS,
                },
            }
            logger.info(
                "FaceFusion submit: endpoint=%s preset=%s output_format=%s timeout_seconds=%s "
                "policy_executionTimeout=%s policy_ttl=%s payload=%s",
                RUNPOD_FACEFUSION_ENDPOINT_ID,
                RUNPOD_FACEFUSION_PRESET,
                RUNPOD_FACEFUSION_OUTPUT_FORMAT,
                RUNPOD_FACEFUSION_TIMEOUT_SECONDS,
                RUNPOD_FACEFUSION_EXECUTION_TIMEOUT_MS,
                RUNPOD_FACEFUSION_TTL_MS,
                _sanitize_for_log(payload),
            )
            response = await client.post(_endpoint_url("/run"), headers=_headers(), json=payload)
            response.raise_for_status()
            data = response.json()

            image = _extract_output_image(data)
            if image:
                return image

            job_id = data.get("id")
            if not job_id:
                logger.error("FaceFusion run response without job id: payload=%s", _sanitize_for_log(data))
                raise _facefusion_error("RunPod FaceFusion did not return a job id or output image")

            last_status = data.get("status")
            last_status_data = data
            logger.info("FaceFusion job created: id=%s status=%s preset=%s", job_id, last_status, RUNPOD_FACEFUSION_PRESET)
            _log_runpod_status(job_id, data, prefix="created")

            while True:
                if asyncio.get_running_loop().time() >= deadline:
                    logger.error(
                        "FaceFusion job timed out: endpoint=%s id=%s timeout_seconds=%s last_payload=%s",
                        RUNPOD_FACEFUSION_ENDPOINT_ID,
                        job_id,
                        RUNPOD_FACEFUSION_TIMEOUT_SECONDS,
                        _sanitize_for_log(last_status_data),
                    )
                    raise _facefusion_error("RunPod FaceFusion job timed out")

                await asyncio.sleep(poll_interval)
                status_response = await client.get(_endpoint_url(f"/status/{job_id}"), headers=_headers())
                status_response.raise_for_status()
                status_data = status_response.json()
                status = status_data.get("status")
                last_status_data = status_data
                _log_runpod_status(job_id, status_data)

                image = _extract_output_image(status_data)
                if image:
                    logger.info("FaceFusion job completed with output.image: id=%s", job_id)
                    return image

                if status in {"COMPLETED", "SUCCEEDED"}:
                    logger.error(
                        "FaceFusion job completed without output.image: id=%s payload=%s",
                        job_id,
                        _sanitize_for_log(status_data),
                    )
                    raise _facefusion_error("RunPod FaceFusion completed without output.image")

                if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                    error = status_data.get("error") or status_data.get("message") or status
                    logger.error(
                        "FaceFusion job terminal status: id=%s status=%s error=%s payload=%s",
                        job_id,
                        status,
                        error,
                        _sanitize_for_log(status_data),
                    )
                    raise _facefusion_error(f"RunPod FaceFusion terminal status: {error}")

                if status != last_status:
                    logger.info("FaceFusion job status: id=%s status=%s", job_id, status)
                    last_status = status
    except ImageProviderError:
        raise
    except Exception as e:
        logger.error("FaceFusion request failed: %s last_payload=%s", e, _sanitize_for_log(last_status_data))
        raise _facefusion_error("RunPod FaceFusion request failed") from e
