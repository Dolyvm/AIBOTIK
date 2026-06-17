"""Small RunPod Serverless client with strict timeout and cancel behavior."""
import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from shared.config import RUNPOD_API_KEY

logger = logging.getLogger(__name__)

SUCCESS_STATUSES = {"COMPLETED", "SUCCEEDED"}
QUEUE_STATUSES = {"IN_QUEUE", "QUEUED"}
FAILURE_STATUSES = {"FAILED", "CANCELLED", "CANCELED", "TIMED_OUT"}
SECRET_KEYS = {"authorization", "api_key", "token", "key", "secret"}
IMAGE_KEYS = {"image", "images", "source_image", "target_image", "data", "base64", "b64_json"}


class RunPodError(RuntimeError):
    pass


class RunPodQueueTimeout(TimeoutError):
    pass


def sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    if isinstance(key, str) and key.lower() in SECRET_KEYS:
        return "<redacted secret>"
    if isinstance(value, str):
        if key in IMAGE_KEYS or value.startswith("data:image/"):
            return _redact_image_value(value)
        if len(value) > 300:
            return f"{value[:300]}...<truncated chars={len(value)}>"
        return value
    if isinstance(value, dict):
        return {str(k): sanitize_for_log(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_log(item) for item in value[:20]]
    return value


def _redact_image_value(value: str) -> str:
    if value.startswith("data:image/"):
        header = value.split(",", 1)[0]
        return f"<redacted data-url {header} chars={len(value)}>"
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"<redacted image-url scheme={parsed.scheme} host={parsed.netloc} chars={len(value)}>"
    return f"<redacted image-string chars={len(value)}>"


def as_data_url(value: str, mime_type: str = "image/png") -> str | None:
    if not value:
        return None
    if value.startswith(("http://", "https://", "data:image/")):
        return value
    value = "".join(value.split())
    try:
        base64.b64decode(value, validate=True)
    except Exception:
        return None
    return f"data:{mime_type};base64,{value}"


def extract_runpod_image(value: Any) -> str | None:
    """Normalize common RunPod/ComfyUI outputs to an image URL or data URL."""
    if isinstance(value, str):
        return as_data_url(value)
    if isinstance(value, list):
        for item in value:
            found = extract_runpod_image(item)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None

    for key in ("url", "image_url", "uri"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            return raw

    for key in ("image", "data", "base64", "b64_json"):
        raw = value.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        image_type = value.get("type")
        if image_type == "s3_url" or raw.startswith(("http://", "https://", "data:image/")):
            return raw
        mime_type = value.get("mime_type") or value.get("content_type") or "image/png"
        found = as_data_url(raw, mime_type)
        if found:
            return found

    for key in ("images", "files", "output", "result"):
        found = extract_runpod_image(value.get(key))
        if found:
            return found

    return None


def extract_runpod_output_image(payload: dict[str, Any]) -> str | None:
    return extract_runpod_image(payload.get("output"))


class RunPodClient:
    def __init__(
        self,
        *,
        endpoint_id: str | None,
        provider: str,
        timeout_seconds: int,
        poll_interval_seconds: float,
        queue_timeout_seconds: int | None = None,
        execution_timeout_ms: int | None = None,
        ttl_ms: int | None = None,
        api_key: str | None = None,
    ):
        self.endpoint_id = endpoint_id
        self.provider = provider
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds))
        if queue_timeout_seconds is None or int(queue_timeout_seconds) <= 0:
            self.queue_timeout_seconds = None
        else:
            self.queue_timeout_seconds = int(queue_timeout_seconds)
        self.execution_timeout_ms = execution_timeout_ms
        self.ttl_ms = ttl_ms
        self.api_key = api_key or RUNPOD_API_KEY

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.endpoint_id)

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise RunPodError("RUNPOD_API_KEY/RUNPOD_KEY is not configured")
        if not self.endpoint_id:
            raise RunPodError(f"{self.provider} RunPod endpoint id is not configured")

    def endpoint_url(self, path: str) -> str:
        self.ensure_configured()
        return f"https://api.runpod.ai/v2/{self.endpoint_id}{path}"

    def headers(self) -> dict[str, str]:
        self.ensure_configured()
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_payload(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {"input": input_payload}
        policy: dict[str, int] = {}
        if self.execution_timeout_ms is not None:
            policy["executionTimeout"] = int(self.execution_timeout_ms)
        if self.ttl_ms is not None:
            policy["ttl"] = int(self.ttl_ms)
        if policy:
            payload["policy"] = policy
        return payload

    async def cancel(self, job_id: str, *, reason: str = "local_cancel") -> bool:
        if not job_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
                response = await client.post(
                    self.endpoint_url(f"/cancel/{job_id}"),
                    headers=self.headers(),
                )
                logger.warning(
                    "RunPod cancel requested: provider=%s endpoint=%s job_id=%s reason=%s status_code=%s payload=%s",
                    self.provider,
                    self.endpoint_id,
                    job_id,
                    reason,
                    response.status_code,
                    sanitize_for_log(_safe_json(response)),
                )
                return response.status_code < 400
        except Exception as e:
            logger.warning(
                "RunPod cancel failed: provider=%s endpoint=%s job_id=%s reason=%s error=%s",
                self.provider,
                self.endpoint_id,
                job_id,
                reason,
                type(e).__name__,
            )
            return False

    async def run(
        self,
        input_payload: dict[str, Any],
        *,
        extract_output: Callable[[dict[str, Any]], Any | None],
        on_job_created: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> Any:
        self.ensure_configured()
        request_timeout = httpx.Timeout(30.0, connect=10.0)
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        job_id: str | None = None
        last_payload: dict[str, Any] | None = None
        queue_started_at: float | None = None

        async with httpx.AsyncClient(timeout=request_timeout) as client:
            try:
                loop = asyncio.get_running_loop()
                payload = self._request_payload(input_payload)
                logger.info(
                    "RunPod submit: provider=%s endpoint=%s timeout_seconds=%s "
                    "queue_timeout_seconds=%s policy=%s payload=%s",
                    self.provider,
                    self.endpoint_id,
                    self.timeout_seconds,
                    self.queue_timeout_seconds,
                    sanitize_for_log(payload.get("policy") or {}),
                    sanitize_for_log(payload),
                )
                response = await client.post(
                    self.endpoint_url("/run"),
                    headers=self.headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                last_payload = data

                immediate = extract_output(data)
                if immediate:
                    return immediate

                job_id = str(data.get("id") or data.get("job_id") or "")
                if not job_id:
                    raise RunPodError(f"{self.provider} did not return a RunPod job id")

                initial_status = str(data.get("status") or "").upper()
                if initial_status in QUEUE_STATUSES:
                    queue_started_at = loop.time()

                logger.info(
                    "RunPod job created: provider=%s endpoint=%s job_id=%s status=%s delayTime=%s executionTime=%s",
                    self.provider,
                    self.endpoint_id,
                    job_id,
                    data.get("status"),
                    data.get("delayTime"),
                    data.get("executionTime"),
                )
                if on_job_created:
                    await on_job_created(job_id, data)

                while True:
                    now = loop.time()
                    if now >= deadline:
                        raise TimeoutError(
                            f"{self.provider} RunPod job timed out after {self.timeout_seconds}s"
                        )
                    if self._queue_timed_out(
                        status=None,
                        queue_started_at=queue_started_at,
                        now=now,
                    ):
                        raise RunPodQueueTimeout(
                            f"{self.provider} RunPod job stayed queued for "
                            f"{self.queue_timeout_seconds}s"
                        )

                    await asyncio.sleep(self.poll_interval_seconds)
                    status_response = await client.get(
                        self.endpoint_url(f"/status/{job_id}"),
                        headers=self.headers(),
                    )
                    status_response.raise_for_status()
                    status_payload = status_response.json()
                    last_payload = status_payload
                    status = str(status_payload.get("status") or "").upper()
                    now = loop.time()
                    if status in QUEUE_STATUSES:
                        if queue_started_at is None:
                            queue_started_at = now
                        queued_ms = int((now - queue_started_at) * 1000)
                    else:
                        queue_started_at = None
                        queued_ms = None
                    logger.info(
                        "RunPod poll: provider=%s endpoint=%s job_id=%s status=%s "
                        "delayTime=%s executionTime=%s queued_ms=%s",
                        self.provider,
                        self.endpoint_id,
                        job_id,
                        status,
                        status_payload.get("delayTime"),
                        status_payload.get("executionTime"),
                        queued_ms,
                    )

                    if self._queue_timed_out(
                        status=status,
                        queue_started_at=queue_started_at,
                        now=now,
                    ):
                        raise RunPodQueueTimeout(
                            f"{self.provider} RunPod job stayed queued for "
                            f"{self.queue_timeout_seconds}s"
                        )

                    output = extract_output(status_payload)
                    if output:
                        return output

                    if status in SUCCESS_STATUSES:
                        raise RunPodError(f"{self.provider} completed without output image")
                    if status in FAILURE_STATUSES:
                        error = (
                            status_payload.get("error")
                            or status_payload.get("message")
                            or status
                        )
                        raise RunPodError(f"{self.provider} terminal status: {error}")
            except asyncio.CancelledError:
                if job_id:
                    await self.cancel(job_id, reason="coroutine_cancelled")
                raise
            except RunPodQueueTimeout as e:
                if job_id:
                    await self.cancel(job_id, reason="queue_timeout")
                logger.error(
                    "RunPod queue timeout: provider=%s endpoint=%s job_id=%s "
                    "queue_timeout_seconds=%s last_payload=%s",
                    self.provider,
                    self.endpoint_id,
                    job_id,
                    self.queue_timeout_seconds,
                    sanitize_for_log(last_payload),
                )
                raise RunPodError(str(e)) from e
            except TimeoutError as e:
                if job_id:
                    await self.cancel(job_id, reason="provider_timeout")
                logger.error(
                    "RunPod provider timeout: provider=%s endpoint=%s job_id=%s last_payload=%s",
                    self.provider,
                    self.endpoint_id,
                    job_id,
                    sanitize_for_log(last_payload),
                )
                raise RunPodError(str(e)) from e
            except RunPodError:
                raise
            except Exception as e:
                if job_id:
                    await self.cancel(job_id, reason="provider_exception")
                logger.error(
                    "RunPod request failed: provider=%s endpoint=%s job_id=%s error=%s payload=%s",
                    self.provider,
                    self.endpoint_id,
                    job_id,
                    type(e).__name__,
                    sanitize_for_log(last_payload),
                )
                raise RunPodError(f"{self.provider} request failed: {type(e).__name__}") from e

    def _queue_timed_out(
        self,
        *,
        status: str | None,
        queue_started_at: float | None,
        now: float,
    ) -> bool:
        if self.queue_timeout_seconds is None or queue_started_at is None:
            return False
        if status is not None and status not in QUEUE_STATUSES:
            return False
        return now - queue_started_at >= self.queue_timeout_seconds


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text[:500]
