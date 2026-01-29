"""Валидаторы для входных данных."""
from typing import TypeVar, Type
from enum import Enum
from .exceptions import ValidationError

T = TypeVar('T', bound=Enum)

VALID_CHAT_TYPES = {"character", "world"}
ALLOWED_METRICS_FIELDS = {
    "affinity", "arousal", "current_location", "current_mood",
    "summary", "msgs_since_summary", "state_meta", "last_auto_photo_at"
}


def validate_chat_type(chat_type: str) -> str:
    if chat_type not in VALID_CHAT_TYPES:
        raise ValidationError("chat_type", f"Must be one of: {VALID_CHAT_TYPES}")
    return chat_type


def validate_enum_value(value: str, enum_class: Type[T], field_name: str) -> T:
    try:
        return enum_class[value.upper()]
    except KeyError:
        valid = [e.name.lower() for e in enum_class]
        raise ValidationError(field_name, f"Must be one of: {valid}")


def validate_metrics_dict(metrics: dict) -> dict:
    invalid = set(metrics.keys()) - ALLOWED_METRICS_FIELDS
    if invalid:
        raise ValidationError("metrics", f"Invalid fields: {invalid}")
    return metrics
