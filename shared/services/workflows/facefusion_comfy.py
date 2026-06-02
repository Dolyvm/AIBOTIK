"""ComfyUI API workflow for FaceFusion image swapping on runpod/worker-comfyui."""

SOURCE_IMAGE_NAME = "facefusion_source.png"
TARGET_IMAGE_NAME = "facefusion_target.png"


def _facefusion_model_and_boost(preset: str) -> tuple[str, str]:
    """Map app presets to Facefusion_comfyui model and pixel boost inputs."""
    supported_models = {
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
    supported_boosts = {"256x256", "512x512", "768x768", "1024x1024"}

    if preset in supported_models:
        return preset, "512x512"
    if preset in supported_boosts:
        return "hyperswap_1c_256", preset

    parts = preset.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        model = f"{parts[0]}_256"
        boost = f"{parts[1]}x{parts[1]}"
        if model in supported_models and boost in supported_boosts:
            return model, boost

    return "hyperswap_1c_256", "512x512"


def build_facefusion_workflow(preset: str, output_format: str) -> dict:
    """Build a ComfyUI API workflow for the Facefusion_comfyui AdvancedSwapFaceImage node."""
    face_swapper_model, pixel_boost = _facefusion_model_and_boost(preset)
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": SOURCE_IMAGE_NAME},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": TARGET_IMAGE_NAME},
        },
        "3": {
            "class_type": "AdvancedSwapFaceImage",
            "inputs": {
                "source_images": ["1", 0],
                "target_image": ["2", 0],
                "api_token": "-1",
                "face_swapper_model": face_swapper_model,
                "face_detector_model": "scrfd",
                "pixel_boost": pixel_boost,
                "face_occluder_model": "none",
                "face_parser_model": "none",
                "face_mask_blur": 0.3,
                "face_selector_mode": "one",
                "face_position": 0,
                "sort_order": "large-small",
                "score_threshold": 0.3,
                "use_box_mask": True,
                "use_occlusion_mask": False,
                "use_area_mask": False,
                "use_region_mask": False,
                "face_mask_areas": "upper-face,lower-face,mouth",
                "face_mask_regions": "skin,nose,mouth,upper-lip,lower-lip",
                "face_mask_padding": "0,0,0,0",
            },
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["3", 0],
                "filename_prefix": f"facefusion_{output_format}",
            },
        },
    }
