"""RunPod direct ONNX FaceFusion worker.

The worker intentionally does not start ComfyUI. It accepts source/target image
data, runs the pinned FaceFusion ONNX path, and returns one final image.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any
from urllib.request import Request, urlopen

import cv2
import numpy as np
import runpod

from model_preflight import find_model, run_preflight

logger = logging.getLogger("facefusion_direct_worker")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

logger.info("worker boot started")
run_preflight()

from facefusion_api.swap_local import swap_faces_local  # noqa: E402

SUPPORTED_MODELS = {
    "hyperswap_1a_256",
    "hyperswap_1b_256",
    "hyperswap_1c_256",
    "ghost_1_256",
    "ghost_2_256",
    "ghost_3_256",
    "hififace_unofficial_256",
    "inswapper_128",
    "inswapper_128_fp16",
    "blendswap_256",
    "simswap_256",
    "simswap_unofficial_512",
    "uniface_256",
}
SUPPORTED_BOOSTS = {"256x256", "512x512", "768x768", "1024x1024"}


def _model_and_boost(preset: str | None) -> tuple[str, str]:
    value = (preset or os.getenv("FACEFUSION_DEFAULT_PRESET") or "hyperswap_1a_512").strip()
    if value in SUPPORTED_MODELS:
        return value, "512x512"
    if value in SUPPORTED_BOOSTS:
        return "hyperswap_1a_256", value

    parts = value.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        model = f"{parts[0]}_256"
        boost = f"{parts[1]}x{parts[1]}"
        if model in SUPPORTED_MODELS and boost in SUPPORTED_BOOSTS:
            return model, boost

    return "hyperswap_1a_256", "512x512"


def _read_image_bytes(value: Any, name: str) -> bytes:
    if isinstance(value, dict):
        value = value.get("image") or value.get("data") or value.get("base64") or value.get("url")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")

    value = value.strip()
    if value.startswith("data:image/"):
        _, encoded = value.split(",", 1)
        return base64.b64decode(encoded)
    if value.startswith(("http://", "https://")):
        request = Request(value, headers={"User-Agent": "runpod-facefusion-direct/1.0"})
        with urlopen(request, timeout=30) as response:
            return response.read()

    return base64.b64decode("".join(value.split()), validate=True)


def _decode_image(value: Any, name: str) -> np.ndarray:
    image_bytes = _read_image_bytes(value, name)
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"{name} is not a decodable image")
    return image


def _encode_image(image: np.ndarray, output_format: str) -> tuple[str, str]:
    normalized = output_format.lower().strip().lstrip(".") or "png"
    if normalized in {"jpg", "jpeg"}:
        extension = ".jpg"
        mime_type = "image/jpeg"
    else:
        extension = ".png"
        mime_type = "image/png"

    ok, encoded = cv2.imencode(extension, image)
    if not ok:
        raise RuntimeError(f"failed to encode output as {extension}")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}", mime_type


def _list_value(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return default
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return default


def _padding_value(value: Any) -> tuple[int, int, int, int]:
    if isinstance(value, str):
        items = [item.strip() for item in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [0, 0, 0, 0]

    parsed = [int(item) for item in items[:4]]
    while len(parsed) < 4:
        parsed.append(0)
    return tuple(parsed[:4])


def handler(job: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    payload = job.get("input") or {}
    if not isinstance(payload, dict):
        raise ValueError("RunPod input must be an object")

    model, default_boost = _model_and_boost(
        payload.get("preset") or payload.get("model") or payload.get("face_swapper_model")
    )
    model = str(payload.get("model") or payload.get("face_swapper_model") or model)
    model = model.removesuffix(".onnx")
    pixel_boost = str(payload.get("pixel_boost") or default_boost)
    detector_model = str(payload.get("face_detector_model") or "scrfd")

    if find_model(f"{model}.onnx") is None:
        raise RuntimeError(f"required FaceFusion model is missing from cache: {model}.onnx")

    source_image = _decode_image(payload.get("source_image"), "source_image")
    target_image = _decode_image(payload.get("target_image"), "target_image")

    logger.info(
        "facefusion started: job_id=%s model=%s pixel_boost=%s detector=%s "
        "source_shape=%s target_shape=%s",
        job.get("id"),
        model,
        pixel_boost,
        detector_model,
        tuple(source_image.shape),
        tuple(target_image.shape),
    )

    result = swap_faces_local(
        source_image=source_image,
        target_image=target_image,
        model_name=model,
        pixel_boost=pixel_boost,
        face_mask_blur=float(payload.get("face_mask_blur", 0.3)),
        face_selector_mode=str(payload.get("face_selector_mode") or "one"),
        face_position=int(payload.get("face_position", 0)),
        sort_order=str(payload.get("sort_order") or "large-small"),
        score_threshold=float(payload.get("score_threshold", 0.3)),
        face_occluder_model=payload.get("face_occluder_model") or "none",
        face_parser_model=payload.get("face_parser_model") or "none",
        face_detector_model=detector_model,
        face_mask_types=_list_value(payload.get("face_mask_types"), ["box"]),
        face_mask_areas=_list_value(
            payload.get("face_mask_areas"),
            ["upper-face", "lower-face", "mouth"],
        ),
        face_mask_regions=_list_value(
            payload.get("face_mask_regions"),
            ["skin", "nose", "mouth", "upper-lip", "lower-lip"],
        ),
        face_mask_padding=_padding_value(payload.get("face_mask_padding")),
    )
    image, mime_type = _encode_image(result, str(payload.get("output_format") or "png"))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info("facefusion completed: job_id=%s elapsed_ms=%s", job.get("id"), elapsed_ms)
    return {
        "image": image,
        "mime_type": mime_type,
        "model": model,
        "pixel_boost": pixel_boost,
        "elapsed_ms": elapsed_ms,
    }


if __name__ == "__main__":
    logger.info("serverless handler registered")
    runpod.serverless.start({"handler": handler})
