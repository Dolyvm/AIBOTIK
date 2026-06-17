"""RunPod FaceFusion provider for custom-photo identity generation."""
import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from shared.config import (
    RUNPOD_FACE_SWAP_ENDPOINT_ID,
    RUNPOD_FACE_SWAP_EXECUTION_TIMEOUT_MS,
    RUNPOD_FACE_SWAP_OUTPUT_FORMAT,
    RUNPOD_FACE_SWAP_POLL_INTERVAL_SECONDS,
    RUNPOD_FACE_SWAP_PRESET,
    RUNPOD_FACE_SWAP_TIMEOUT_SECONDS,
    RUNPOD_FACE_SWAP_TTL_MS,
)
from shared.services.runpod_client import (
    RunPodClient,
    RunPodError,
    as_data_url,
    extract_runpod_output_image,
)
from shared.services.workflows.facefusion_direct import build_facefusion_input

logger = logging.getLogger(__name__)


class FaceFusionError(RuntimeError):
    pass


def facefusion_client() -> RunPodClient:
    return RunPodClient(
        endpoint_id=RUNPOD_FACE_SWAP_ENDPOINT_ID,
        provider="runpod_facefusion",
        timeout_seconds=RUNPOD_FACE_SWAP_TIMEOUT_SECONDS,
        poll_interval_seconds=RUNPOD_FACE_SWAP_POLL_INTERVAL_SECONDS,
        execution_timeout_ms=RUNPOD_FACE_SWAP_EXECUTION_TIMEOUT_MS,
        ttl_ms=RUNPOD_FACE_SWAP_TTL_MS,
    )


def is_configured() -> bool:
    return facefusion_client().is_configured


async def cancel(job_id: str, *, reason: str = "app_cancel") -> bool:
    return await facefusion_client().cancel(job_id, reason=reason)


async def _prepare_direct_image(client: httpx.AsyncClient, image: str, name: str) -> str:
    if image.startswith("data:image/"):
        return image

    if image.startswith(("http://", "https://")):
        response = await client.get(image)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/png").split(";", 1)[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    found = as_data_url(image)
    if found:
        return found

    raise FaceFusionError(f"Unsupported FaceFusion image input for {name}")


async def swap_face(
    *,
    source_image: str,
    target_image: str,
    on_job_created: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> str:
    """Run FaceFusion and return only the final swapped image."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as image_client:
            source_image_data = await _prepare_direct_image(
                image_client,
                source_image,
                "source_image",
            )
            target_image_data = await _prepare_direct_image(
                image_client,
                target_image,
                "target_image",
            )
        output = await facefusion_client().run(
            build_facefusion_input(
                source_image=source_image_data,
                target_image=target_image_data,
                preset=RUNPOD_FACE_SWAP_PRESET,
                output_format=RUNPOD_FACE_SWAP_OUTPUT_FORMAT,
            ),
            extract_output=extract_runpod_output_image,
            on_job_created=on_job_created,
        )
    except (RunPodError, httpx.HTTPError) as e:
        raise FaceFusionError(str(e)) from e

    if not isinstance(output, str) or not output:
        raise FaceFusionError("RunPod FaceFusion returned an empty image")
    logger.info("FaceFusion swap completed: endpoint=%s", RUNPOD_FACE_SWAP_ENDPOINT_ID)
    return output
