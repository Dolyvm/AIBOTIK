"""Fail-fast model preflight for the RunPod Manhwa ComfyUI worker."""
from importlib import util
from pathlib import Path


try:
    from .preflight import run_preflight
except ImportError:
    spec = util.spec_from_file_location(
        "manhwa_model_preflight",
        Path(__file__).with_name("preflight.py"),
    )
    if spec is None or spec.loader is None:
        raise
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_preflight = module.run_preflight


run_preflight()

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
