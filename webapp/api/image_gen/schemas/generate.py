import enum
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, field_validator


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


@dataclass
class NSFWLevel:
    neutral: PromptLayer = PromptLayer(
        prompt="fully clothed",
        negative_prompt="nudity, sexual act, lingerie, NSFW, nsfw"
    )
    light: PromptLayer = PromptLayer(
        prompt="sensual mood, teasing expression, fully clothed",
        negative_prompt="nudity, sexual act"
    )
    erotic: PromptLayer = PromptLayer(
        prompt="erotic, intimate pose, underwear, panties",
        negative_prompt="explicit, sex, penetration"
    )
    nudity: PromptLayer = PromptLayer(
        prompt="full nudity, erotic",
        negative_prompt="penetration, explicit sex"
    )
    explicit: PromptLayer = PromptLayer(
        prompt="explicit, erotic, sexual scene, nsfw",
        negative_prompt="violence, extreme fetish"
    )
    extreme: PromptLayer = PromptLayer(
        prompt="extreme erotic, fetish, explicit, nsfw",
        negative_prompt=""
    )


NSFW_LEVELS_LIST = [
    PromptLayer(
        prompt="fully clothed",
        negative_prompt="nudity, sexual act, lingerie, NSFW, nsfw"
    ),
    PromptLayer(
        prompt="sensual mood, teasing expression, fully clothed",
        negative_prompt="nudity, sexual act"
    ),
    PromptLayer(
        prompt="aroused, showing her bra, touching her ass",
        negative_prompt="nsfw"
    ),
    PromptLayer(
        prompt="showing her naked body",
        negative_prompt="penetration, explicit sex"
    ),
    PromptLayer(
        prompt="showing her naked body and shaved pussy, no clothes",
        negative_prompt=""
    ),
    PromptLayer(
        prompt="extreme erotic, explicit, nsfw, orgasm, extremely aroused, masturbating, touching her pussy",
        negative_prompt=""
    )
]


ANIME_BASE_POS = "(anime style:1.2), 1girl, masterpiece, absurdres, best quality, amazing quality"
ANIME_BASE_NEG = "2girls, blurry face, blurry eyes, lowres, worst quality, low quality, bad anatomy, bad hands"
REAL_BASE_POS = ""
REAL_BASE_NEG = ""


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

    # @field_validator('nsfw_level', mode='before')
    # def validate_nsfw_level(cls, v):
    #     if isinstance(v, str):
    #         return getattr(NSFWLevel, v)
    #     raise ValueError

    def build_prompt(self, build_as_type: ModelType = None) -> tuple[str, str]:
        prompt_parts = []
        negative_parts = []

        if build_as_type == "anime":
            prompt_parts.append(ANIME_BASE_POS)
            negative_parts.append(ANIME_BASE_NEG)
        elif build_as_type == "real":
            prompt_parts.append(REAL_BASE_POS)
            negative_parts.append(REAL_BASE_NEG)

        for field_name, _ in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            if not value:
                continue

            if field_name == "nsfw_level":
                # value: int
                nsfw_level = NSFW_LEVELS_LIST[value]
                prompt_parts.append(nsfw_level.prompt)
                negative_parts.append(nsfw_level.negative_prompt)
                continue

            prompt_parts.append(value)
        prompt = ", ".join(prompt_parts)
        negative_prompt = ", ".join(negative_parts)

        return prompt, negative_prompt

