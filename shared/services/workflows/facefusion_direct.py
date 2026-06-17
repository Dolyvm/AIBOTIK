"""Direct RunPod FaceFusion payload builder."""

SUPPORTED_FACEFUSION_MODELS = {
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
SUPPORTED_PIXEL_BOOSTS = {"256x256", "512x512", "768x768", "1024x1024"}


def facefusion_model_and_boost(preset: str) -> tuple[str, str]:
    if preset in SUPPORTED_FACEFUSION_MODELS:
        return preset, "512x512"
    if preset in SUPPORTED_PIXEL_BOOSTS:
        return "hyperswap_1a_256", preset

    parts = preset.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        model = f"{parts[0]}_256"
        boost = f"{parts[1]}x{parts[1]}"
        if model in SUPPORTED_FACEFUSION_MODELS and boost in SUPPORTED_PIXEL_BOOSTS:
            return model, boost

    return "hyperswap_1a_256", "512x512"


def build_facefusion_input(
    *,
    source_image: str,
    target_image: str,
    preset: str,
    output_format: str,
) -> dict[str, object]:
    model, pixel_boost = facefusion_model_and_boost(preset)
    return {
        "source_image": source_image,
        "target_image": target_image,
        "model": model,
        "pixel_boost": pixel_boost,
        "face_detector_model": "scrfd",
        "return_base64": True,
        "output_format": output_format,
    }
