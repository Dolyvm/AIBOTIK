# RunPod FaceFusion worker logging

Use this logging shape inside the separate RunPod FaceFusion worker image. The app
expects the same `job_id` to appear in both local `botik-worker-1` logs and RunPod
endpoint logs.

Do not log API keys, full data URLs, image bytes, or private image URLs.

```python
import logging
import time

logger = logging.getLogger("facefusion_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _image_summary(value: str | None) -> str:
    if not value:
        return "missing"
    if value.startswith("data:image/"):
        header = value.split(",", 1)[0]
        return f"data_url:{header}:chars={len(value)}"
    return f"url_or_path:chars={len(value)}"


def handler(job):
    started_at = time.monotonic()
    job_id = job.get("id") or job.get("job_id") or "unknown"
    try:
        logger.info("job received: id=%s", job_id)
        payload = job.get("input") or {}
        logger.info(
            "input validated: id=%s preset=%s output_format=%s source=%s target=%s",
            job_id,
            payload.get("preset"),
            payload.get("output_format"),
            _image_summary(payload.get("source_image")),
            _image_summary(payload.get("target_image")),
        )

        logger.info("source/target decoded: id=%s", job_id)
        logger.info("facefusion started: id=%s", job_id)
        # Run FaceFusion here.
        logger.info("facefusion completed: id=%s elapsed_ms=%d", job_id, (time.monotonic() - started_at) * 1000)

        result = {"image": "..."}
        logger.info("returning output.image: id=%s", job_id)
        return result
    except Exception as exc:
        logger.exception("job failed: id=%s error=%s", job_id, exc)
        raise
```

Expected boot logs:

```text
worker boot started
comfy/facefusion dependencies ready
serverless handler registered
```
