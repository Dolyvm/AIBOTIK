"""Startup model and ONNXRuntime checks for the direct FaceFusion worker."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL_DIRS = ":".join(
    [
        "/runpod-volume/huggingface-cache/hub",
        "/runpod-volume/models/facefusion",
        "/runpod-volume/models",
        "/workspace/models/facefusion",
        "/workspace/models",
        "/opt/Facefusion_comfyui/models",
    ]
)


def _split_env(name: str, default: str) -> list[Path]:
    value = os.getenv(name, default)
    return [Path(item).expanduser() for item in value.split(":") if item.strip()]


def _required_models() -> list[str]:
    value = os.getenv(
        "FACEFUSION_REQUIRED_MODELS",
        "hyperswap_1a_256.onnx,scrfd_2.5g.onnx,arcface_w600k_r50.onnx",
    )
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _candidate_names(name: str) -> list[str]:
    names = [name]
    if not name.endswith(".onnx"):
        names.append(f"{name}.onnx")
    return names


def find_model(name: str) -> Path | None:
    lowered = {item.lower() for item in _candidate_names(name)}
    for root in _split_env("FACEFUSION_MODEL_DIRS", DEFAULT_MODEL_DIRS):
        if not root.exists():
            continue
        for candidate in _candidate_names(name):
            direct = root / candidate
            if direct.is_file():
                return direct
        for path in root.rglob("*"):
            if path.is_file() and path.name.lower() in lowered:
                return path
    return None


def _model_from_preset(preset: str) -> str:
    if preset.endswith(".onnx"):
        return preset.removesuffix(".onnx")
    if preset in {"256x256", "512x512", "768x768", "1024x1024"}:
        return "hyperswap_1a_256"
    parts = preset.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return f"{parts[0]}_256"
    return preset or "hyperswap_1a_256"


def run_preflight() -> None:
    if os.getenv("RUNPOD_SKIP_MODEL_PREFLIGHT", "").lower() in {"1", "true", "yes"}:
        print("FaceFusion models preflight skipped by RUNPOD_SKIP_MODEL_PREFLIGHT")
        return

    missing = [name for name in _required_models() if find_model(name) is None]
    if missing:
        roots = ", ".join(
            str(root) for root in _split_env("FACEFUSION_MODEL_DIRS", DEFAULT_MODEL_DIRS)
        )
        raise RuntimeError(
            "FaceFusion models preflight failed; missing "
            f"{missing}. Mount models via RunPod Cached Models. Searched: {roots}"
        )

    import onnxruntime as ort

    providers = ort.get_available_providers()
    if "CUDAExecutionProvider" not in providers:
        raise RuntimeError(f"FaceFusion CUDA preflight failed; ONNXRuntime providers={providers}")
    print(f"ONNXRuntime providers include CUDAExecutionProvider: providers={providers}")

    if os.getenv("FACEFUSION_PRELOAD_MODELS", "1").lower() not in {"0", "false", "no"}:
        from facefusion_api.detection.detector import get_face_detector
        from facefusion_api.models.swapper import get_local_swapper

        model_name = _model_from_preset(os.getenv("FACEFUSION_DEFAULT_PRESET", "hyperswap_1a_512"))
        detector = get_face_detector("scrfd")
        if not detector.initialize():
            raise RuntimeError("FaceFusion detector preflight failed")
        swapper = get_local_swapper(model_name)
        if not swapper.initialize():
            raise RuntimeError(f"FaceFusion swapper preflight failed for {model_name}")

    print(
        "FaceFusion models preflight passed: "
        f"required={_required_models()} providers={providers}"
    )
