import random


MANHWA_CHECKPOINT = "wai_illustrious_v16.safetensors"
MANHWA_NIJI_LORA = "niji_semi_realism_v4.safetensors"
MANHWA_MEN_LORA = "semi_realistic_anime_men.safetensors"

MANHWA_BASE_POSITIVE = (
    "masterpiece, best quality, amazing quality, very aesthetic, "
    "SemiNrealism, semi-realistic, male, 1boy, solo, male focus, adult man, "
    "bishounen, handsome man, korean manhwa style, soft niji style, "
    "watercolor-like rendering, painterly"
)

MANHWA_BASE_NEGATIVE = (
    "female, 1girl, woman, child, teen, shota, boyish, "
    "low quality, worst quality, blurry, bad anatomy, bad hands, "
    "extra fingers, missing fingers, deformed face, ugly, "
    "flat lighting, simple background, text, watermark, signature, censored"
)


def build_manhwa_workflow(
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    *,
    width: int = 768,
    height: int = 1152,
    steps: int = 30,
    cfg: float = 5.0,
    niji_strength: float = 0.65,
    men_strength: float = 0.45,
) -> dict:
    """Build a ComfyUI API workflow for the tested Illustrious manhwa stack."""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": MANHWA_CHECKPOINT},
        },
        "2": {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["1", 1], "stop_at_clip_layer": -2},
        },
        "3": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["2", 0],
                "lora_name": MANHWA_NIJI_LORA,
                "strength_model": niji_strength,
                "strength_clip": niji_strength,
            },
        },
        "4": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["3", 0],
                "clip": ["3", 1],
                "lora_name": MANHWA_MEN_LORA,
                "strength_model": men_strength,
                "strength_clip": men_strength,
            },
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": positive_prompt},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": negative_prompt},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
                "seed": seed if seed >= 0 else random.randint(0, 2**31 - 1),
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"images": ["9", 0], "filename_prefix": "manhwa"},
        },
    }
