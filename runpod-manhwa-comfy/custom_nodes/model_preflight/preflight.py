"""Locate cached Manhwa models before ComfyUI validates workflows."""
import os
from pathlib import Path


DEFAULT_CHECKPOINT_ROOTS = ":".join(
    [
        "/runpod-volume/models/checkpoints",
        "/runpod-volume/huggingface-cache/hub",
        "/workspace/models/checkpoints",
        "/comfyui/models/checkpoints",
    ]
)
DEFAULT_LORA_ROOTS = ":".join(
    [
        "/runpod-volume/models/loras",
        "/runpod-volume/huggingface-cache/hub",
        "/workspace/models/loras",
        "/comfyui/models/loras",
    ]
)


def _items(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [
        item.strip()
        for item in value.replace(";", ",").split(",")
        if item.strip()
    ]


def _roots(name: str, default: str) -> list[Path]:
    value = os.getenv(name, default)
    return [Path(item).expanduser() for item in value.split(":") if item.strip()]


def _find_file(filename: str, roots: list[Path]) -> Path | None:
    lowered = filename.lower()
    for root in roots:
        if not root.exists():
            continue
        direct = root / filename
        if direct.exists() and direct.is_file():
            return direct
        for path in root.rglob("*"):
            if path.is_file() and path.name.lower() == lowered:
                return path
    return None


def _link_file(filename: str, source: Path, targets: list[Path]) -> dict[str, str]:
    linked = {}
    for root in targets:
        root.mkdir(parents=True, exist_ok=True)
        destination = root / filename
        if destination.exists() or destination.is_symlink():
            if destination.resolve() == source.resolve():
                linked[str(destination)] = "exists"
            else:
                linked[str(destination)] = f"exists: {destination.resolve()}"
            continue
        destination.symlink_to(source)
        linked[str(destination)] = str(source)
    return linked


def _check(
    kind: str,
    required: list[str],
    roots: list[Path],
    targets: list[Path],
) -> dict[str, dict[str, object]]:
    missing = []
    found = {}
    for filename in required:
        path = _find_file(filename, roots)
        if path is None:
            missing.append(filename)
        else:
            found[filename] = {
                "source": str(path),
                "targets": _link_file(filename, path, targets),
            }
    if missing:
        raise RuntimeError(
            f"Manhwa {kind} preflight failed; missing {missing}. "
            "Mount models via RunPod Cached Models or Network Volume. "
            f"Searched: {', '.join(str(root) for root in roots)}"
        )
    return found


def run_preflight() -> None:
    skip_value = os.getenv("RUNPOD_SKIP_MODEL_PREFLIGHT", "").lower()
    if skip_value in {"1", "true", "yes"}:
        print("Manhwa models preflight skipped by RUNPOD_SKIP_MODEL_PREFLIGHT")
        return

    checkpoints = _check(
        "checkpoint",
        _items("MANHWA_REQUIRED_CHECKPOINTS", "wai_illustrious_v16.safetensors"),
        _roots("MANHWA_CHECKPOINT_DIRS", DEFAULT_CHECKPOINT_ROOTS),
        _roots("MANHWA_CHECKPOINT_TARGET_DIRS", "/comfyui/models/checkpoints"),
    )
    loras = _check(
        "LoRA",
        _items(
            "MANHWA_REQUIRED_LORAS",
            "niji_semi_realism_v4.safetensors,semi_realistic_anime_men.safetensors",
        ),
        _roots("MANHWA_LORA_DIRS", DEFAULT_LORA_ROOTS),
        _roots("MANHWA_LORA_TARGET_DIRS", "/comfyui/models/loras"),
    )
    print(f"Manhwa models preflight passed: checkpoints={checkpoints} loras={loras}")


if __name__ == "__main__":
    run_preflight()
