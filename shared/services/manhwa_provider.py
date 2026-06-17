"""RunPod provider for Manhwa/Illustrious image generation."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from shared.config import (
    RUNPOD_MANHWA_ENDPOINT_ID,
    RUNPOD_MANHWA_EXECUTION_TIMEOUT_MS,
    RUNPOD_MANHWA_POLL_INTERVAL_SECONDS,
    RUNPOD_MANHWA_QUEUE_TIMEOUT_SECONDS,
    RUNPOD_MANHWA_TIMEOUT_SECONDS,
    RUNPOD_MANHWA_TTL_MS,
)
from shared.services.runpod_client import RunPodClient, RunPodError, extract_runpod_output_image
from shared.services.workflows.manhwa_illustrious import (
    MANHWA_BASE_NEGATIVE,
    MANHWA_BASE_POSITIVE,
    build_manhwa_workflow,
)

logger = logging.getLogger(__name__)

CLIP_MAX_WORDS = 120


class ManhwaProviderError(RuntimeError):
    pass


def manhwa_client() -> RunPodClient:
    return RunPodClient(
        endpoint_id=RUNPOD_MANHWA_ENDPOINT_ID,
        provider="runpod_manhwa",
        timeout_seconds=RUNPOD_MANHWA_TIMEOUT_SECONDS,
        poll_interval_seconds=RUNPOD_MANHWA_POLL_INTERVAL_SECONDS,
        queue_timeout_seconds=RUNPOD_MANHWA_QUEUE_TIMEOUT_SECONDS,
        execution_timeout_ms=RUNPOD_MANHWA_EXECUTION_TIMEOUT_MS,
        ttl_ms=RUNPOD_MANHWA_TTL_MS,
    )


def is_configured() -> bool:
    return manhwa_client().is_configured


async def cancel(job_id: str, *, reason: str = "app_cancel") -> bool:
    return await manhwa_client().cancel(job_id, reason=reason)


def _truncate_for_clip(prompt: str, max_words: int = CLIP_MAX_WORDS) -> str:
    parts = [p.strip() for p in (prompt or "").split(",") if p.strip()]
    result: list[str] = []
    word_count = 0
    for part in parts:
        part_words = len(part.split())
        if word_count + part_words > max_words:
            break
        result.append(part)
        word_count += part_words
    truncated = ", ".join(result) if result else (prompt or "")[:300]
    if len(result) < len(parts):
        logger.info(
            "Manhwa prompt truncated: tags_before=%s tags_after=%s words=%s",
            len(parts),
            len(result),
            word_count,
        )
    return truncated


def build_provider_prompts(positive_prompt: str, negative_prompt: str = "") -> dict[str, str]:
    """Return the exact positive/negative prompts sent to the RunPod workflow."""
    return {
        "positive_prompt": _truncate_for_clip(f"{MANHWA_BASE_POSITIVE}, {positive_prompt}"),
        "negative_prompt": _truncate_for_clip(f"{MANHWA_BASE_NEGATIVE}, {negative_prompt}"),
    }


async def generate(
    *,
    positive_prompt: str,
    negative_prompt: str = "",
    seed: int = -1,
    on_job_created: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> str:
    provider_prompts = build_provider_prompts(positive_prompt, negative_prompt)
    workflow = build_manhwa_workflow(
        provider_prompts["positive_prompt"],
        provider_prompts["negative_prompt"],
        seed=seed,
    )

    try:
        output = await manhwa_client().run(
            {
                "workflow": workflow,
                "prompt": workflow,
                "return_base64": True,
            },
            extract_output=extract_runpod_output_image,
            on_job_created=on_job_created,
        )
    except RunPodError as e:
        raise ManhwaProviderError(str(e)) from e

    if not isinstance(output, str) or not output:
        raise ManhwaProviderError("RunPod Manhwa returned an empty image")
    logger.info("Manhwa generation completed: endpoint=%s", RUNPOD_MANHWA_ENDPOINT_ID)
    return output
