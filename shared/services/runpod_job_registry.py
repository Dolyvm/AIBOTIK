"""Helpers for canceling RunPod jobs recorded on local image generation jobs."""
import logging
from typing import Any, Mapping

from shared.services import facefusion_provider, manhwa_provider

logger = logging.getLogger(__name__)


def extract_runpod_jobs(payload: Mapping[str, Any] | None) -> list[dict[str, str]]:
    raw_jobs = (payload or {}).get("runpod_jobs") if isinstance(payload, Mapping) else None
    if not isinstance(raw_jobs, list):
        return []
    result = []
    for item in raw_jobs:
        if not isinstance(item, Mapping):
            continue
        provider = str(item.get("provider") or "").strip()
        job_id = str(item.get("job_id") or "").strip()
        if provider and job_id:
            result.append(
                {
                    "provider": provider,
                    "job_id": job_id,
                    "endpoint_id": str(item.get("endpoint_id") or "").strip(),
                }
            )
    return result


async def cancel_recorded_runpod_jobs(
    payload: Mapping[str, Any] | None,
    *,
    reason: str,
) -> int:
    canceled = 0
    for item in extract_runpod_jobs(payload):
        provider = item["provider"]
        job_id = item["job_id"]
        if provider == "runpod_facefusion":
            ok = await facefusion_provider.cancel(job_id, reason=reason)
        elif provider == "runpod_manhwa":
            ok = await manhwa_provider.cancel(job_id, reason=reason)
        else:
            logger.warning(
                "Unknown RunPod provider for cancel: provider=%s job_id=%s reason=%s",
                provider,
                job_id,
                reason,
            )
            ok = False
        canceled += int(bool(ok))
    return canceled
