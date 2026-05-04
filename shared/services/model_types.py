SUPPORTED_MODEL_TYPES = {"anime", "real", "manhwa"}


def is_supported_model_type(model_type: str | None) -> bool:
    return model_type in SUPPORTED_MODEL_TYPES


def validate_model_gender(model_type: str | None, gender: str | None) -> None:
    if not is_supported_model_type(model_type):
        raise ValueError(f"Unsupported model_type: {model_type}")
    if model_type == "manhwa" and gender != "male":
        raise ValueError("model_type='manhwa' is only available for male characters")
