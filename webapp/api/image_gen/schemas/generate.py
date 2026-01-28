import enum
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel
from shared.services.prompt_service import get_prompt


class ModelType(enum.Enum):
    real = "real"
    anime = "anime"


class ImageSize(BaseModel):
    width: int = 1024
    height: int = 1024


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str
    model_type: ModelType
    size: ImageSize = ImageSize(width=1024, height=1024)
    allow_nsfw: bool = True


class TerminatePodRequest(BaseModel):
    pod_id: str


@dataclass(frozen=True)
class PromptLayer:
    prompt: str = ""
    negative_prompt: str = ""


def _get_nsfw_levels() -> list[PromptLayer]:
    return [
        PromptLayer(
            prompt=get_prompt("nsfw_level_0"),
            negative_prompt=get_prompt("nsfw_level_0_neg")
        ),
        PromptLayer(
            prompt=get_prompt("nsfw_level_1"),
            negative_prompt=get_prompt("nsfw_level_1_neg")
        ),
        PromptLayer(
            prompt=get_prompt("nsfw_level_2"),
            negative_prompt=get_prompt("nsfw_level_2_neg")
        ),
        PromptLayer(
            prompt=get_prompt("nsfw_level_3"),
            negative_prompt=get_prompt("nsfw_level_3_neg")
        ),
        PromptLayer(
            prompt=get_prompt("nsfw_level_4"),
            negative_prompt=get_prompt("nsfw_level_4_neg")
        ),
        PromptLayer(
            prompt=get_prompt("nsfw_level_5"),
            negative_prompt=get_prompt("nsfw_level_5_neg")
        ),
    ]


_NSFW_LEVELS_CACHE = None


def get_nsfw_levels() -> list[PromptLayer]:
    global _NSFW_LEVELS_CACHE
    if _NSFW_LEVELS_CACHE is None:
        _NSFW_LEVELS_CACHE = _get_nsfw_levels()
    return _NSFW_LEVELS_CACHE


def invalidate_nsfw_levels_cache():
    global _NSFW_LEVELS_CACHE
    _NSFW_LEVELS_CACHE = None


def get_anime_base_positive() -> str:
    return get_prompt("anime_base_positive")


def get_anime_base_negative() -> str:
    return get_prompt("anime_base_negative")


class Prompt(BaseModel):
    character_base: Optional[str] = ""
    signature: Optional[str] = ""
    body_state: Optional[str] = ""
    facial_expression: Optional[str] = ""
    clothing: Optional[str] = ""
    environment: Optional[str] = ""
    action: Optional[str] = ""
    camera: Optional[str] = ""
    style: Optional[str] = ""
    nsfw_level: int = 0

    @classmethod
    def from_character(
        cls,
        character: dict,
        outfit_key: str = "default_outfit",
        nsfw_level: int = 0,
        environment: str = ""
    ) -> "Prompt":
        visual = character.get("visual", {})
        model_type = character.get("model_type", "real")

        if outfit_key == "default_outfit":
            clothing = visual.get("default_outfit", "")
        else:
            wardrobe = visual.get("wardrobe", {})
            clothing = wardrobe.get(outfit_key, visual.get("default_outfit", ""))

        appearance = visual.get("appearance", character.get("appearance", ""))

        if model_type == "anime":
            character_base = appearance
            style = ""
        else:
            body = visual.get("body", "")
            face = visual.get("face", "")
            style = visual.get("style_tags", "")
            character_base = ", ".join(filter(None, [appearance, body, face]))

        return cls(
            character_base=character_base,
            clothing=clothing,
            style=style,
            environment=environment,
            nsfw_level=nsfw_level
        )

    def build_prompt(self, build_as_type: ModelType = None) -> tuple[str, str]:
        prompt_parts = []
        negative_parts = []

        if build_as_type == "anime":
            prompt_parts.append(get_anime_base_positive())
            negative_parts.append(get_anime_base_negative())

        for field_name, _ in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            if value == "":
                continue

            if field_name == "nsfw_level":
                # value: int
                nsfw_level = get_nsfw_levels()[value]
                prompt_parts.append(nsfw_level.prompt)
                negative_parts.append(nsfw_level.negative_prompt)
                continue

            prompt_parts.append(value)
        prompt = ", ".join(prompt_parts)
        negative_prompt = ", ".join(negative_parts)

        return prompt, negative_prompt
