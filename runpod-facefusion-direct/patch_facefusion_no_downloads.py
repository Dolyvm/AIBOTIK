"""Patch the pinned Facefusion_comfyui checkout for direct worker use."""
from __future__ import annotations

import sys
from pathlib import Path


def _patch_package_init(repo: Path) -> None:
    (repo / "facefusion_api" / "__init__.py").write_text(
        '"""Direct worker package marker; ComfyUI node imports are intentionally disabled."""\n',
        encoding="utf-8",
    )


def _patch_utils(repo: Path) -> None:
    path = repo / "facefusion_api" / "utils.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "import torch\n",
        "try:\n"
        "    import torch\n"
        "except Exception:\n"
        "    torch = None\n",
    )
    text = text.replace(
        "from torch import Tensor\n",
        "try:\n"
        "    from torch import Tensor\n"
        "except Exception:\n"
        "    Tensor = Any\n",
    )

    marker = "def get_model_path(model_name: str) -> str:"
    index = text.index(marker)
    replacement = r'''
def _split_model_dirs() -> List[str]:
    raw = os.getenv(
        'FACEFUSION_MODEL_DIRS',
        ':'.join([
            '/runpod-volume/huggingface-cache/hub',
            '/runpod-volume/models/facefusion',
            '/runpod-volume/models',
            '/workspace/models/facefusion',
            '/workspace/models',
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models'),
        ])
    )
    return [item for item in raw.split(':') if item.strip()]


def _candidate_model_names(model_name: str) -> List[str]:
    names = [model_name]
    if not model_name.endswith('.onnx'):
        names.append(f'{model_name}.onnx')
    return names


def _find_model_file(model_name: str) -> Optional[str]:
    lowered = {item.lower() for item in _candidate_model_names(model_name)}
    for root in _split_model_dirs():
        if not os.path.isdir(root):
            continue
        for candidate in _candidate_model_names(model_name):
            direct = os.path.join(root, candidate)
            if os.path.isfile(direct):
                return direct
        for current_root, _, filenames in os.walk(root):
            for filename in filenames:
                if filename.lower() in lowered:
                    return os.path.join(current_root, filename)
    return None


def get_model_path(model_name: str) -> str:
    """Resolve a model from RunPod Cached Models without downloading."""
    found = _find_model_file(model_name)
    if found:
        return found
    fallback = os.getenv(
        'FACEFUSION_FALLBACK_MODEL_DIR',
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
    )
    return os.path.join(fallback, model_name)


def ensure_model_exists(
    model_name: str,
    download_url: Optional[str] = None,
    expected_hash: Optional[str] = None,
) -> bool:
    """Ensure a model exists, with runtime downloads disabled by default."""
    model_path = get_model_path(model_name)
    if os.path.exists(model_path):
        if expected_hash is None or verify_file_hash(model_path, expected_hash):
            return True

    downloads_disabled = (
        os.getenv('FACEFUSION_DISABLE_MODEL_DOWNLOADS', '1').lower()
        not in {'0', 'false', 'no'}
    )
    if downloads_disabled:
        print(f"Model {model_name} not found in FACEFUSION_MODEL_DIRS; runtime download disabled")
        return False

    if download_url:
        print(f"Model {model_name} not found, downloading...")
        return download_file(download_url, model_path, expected_hash)

    return False
'''
    path.write_text(text[:index] + replacement.lstrip(), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_facefusion_no_downloads.py /path/to/Facefusion_comfyui")
    repo = Path(sys.argv[1])
    _patch_package_init(repo)
    _patch_utils(repo)


if __name__ == "__main__":
    main()
