import enum
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel
from shared.services.prompt_service import get_prompt
from shared.services.cache import get_cache

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

async def _build_nsfw_levels() -> list[dict]:
    levels = []
    for i in range(6):
        prompt = await get_prompt(f"nsfw_level_{i}")
        negative_prompt = await get_prompt(f"nsfw_level_{i}_neg")
        levels.append({
            "prompt": prompt,
            "negative_prompt": negative_prompt
        })
    return levels

async def get_nsfw_levels() -> list[PromptLayer]:
    cache = get_cache()

    if cache:
        cached = await cache.get_nsfw_levels()
        if cached:
            return [PromptLayer(prompt=l["prompt"], negative_prompt=l["negative_prompt"]) for l in cached]

    levels_data = await _build_nsfw_levels()

    if cache:
        await cache.set_nsfw_levels(levels_data)

    return [PromptLayer(prompt=l["prompt"], negative_prompt=l["negative_prompt"]) for l in levels_data]

async def invalidate_nsfw_levels_cache():
    cache = get_cache()
    if cache:
        await cache.invalidate_nsfw_levels()

async def get_anime_base_positive() -> str:
    return await get_prompt("anime_base_positive")

async def get_anime_base_negative() -> str:
    return await get_prompt("anime_base_negative")

AGE_INTERVAL_MAP = {
    "18": "18-20 years old",
    "25": "20-30 years old",
    "35": "30-40 years old",
    "45": "50 years old",
    "70": "60-70 years old"
}

SKIN_BY_AGE = {
    "18": "smooth youthful skin",
    "25": "smooth skin",
    "35": "clear mature skin, refined features",
    "45": "mature skin, elegant features",
    "70": "mature skin with character, distinguished features"
}


class Prompt(BaseModel):
    character_base: Optional[str] = ""
    signature: Optional[str] = ""
    body_state: Optional[str] = ""
    facial_expression: Optional[str] = ""
    scene_details: Optional[str] = ""
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

        # Если appearance пуст - строим из отдельных полей (пользовательские персонажи)
        if not appearance and visual.get("age"):
            if model_type == "anime":
                parts = ["1girl", "anime girl"]
                age = visual.get("age")
                if age:
                    parts.append(AGE_INTERVAL_MAP.get(age, f"{age} years old"))
                if visual.get("eye_color"):
                    parts.append(f"{visual['eye_color']} eyes")
                if visual.get("hair_color"):
                    parts.append(f"{visual['hair_color']} hair")
                if visual.get("haircut"):
                    parts.append(visual["haircut"])
                if visual.get("body_type"):
                    parts.append(visual["body_type"])
                if visual.get("boobs"):
                    parts.append(visual["boobs"])
                if visual.get("ass"):
                    parts.append(visual["ass"])
                appearance = ", ".join(parts)
            else:
                # Для real модели строим описание
                parts = []
                nationality = visual.get("nationality")
                if nationality:
                    parts.append(f"{nationality} woman")
                age = visual.get("age")
                if age:
                    parts.append(f"({age})")
                    skin = SKIN_BY_AGE.get(age, "smooth skin")
                    parts.append(f"with {skin}")
                if visual.get("hair_color") and visual.get("haircut"):
                    parts.append(f"{visual['hair_color']} hair with {visual['haircut']}")
                elif visual.get("hair_color"):
                    parts.append(f"{visual['hair_color']} hair")
                if visual.get("eye_color"):
                    parts.append(f"beautiful {visual['eye_color']} eyes")
                if visual.get("body_type"):
                    parts.append(visual["body_type"])
                if visual.get("boobs"):
                    parts.append(f"with {visual['boobs']}")
                if visual.get("ass"):
                    parts.append(f"and {visual['ass']}")
                appearance = ", ".join(parts)

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

    async def build_prompt(self, build_as_type: ModelType = None) -> tuple[str, str]:
        prompt_parts = []
        negative_parts = []

        if build_as_type == "anime":
            base_positive = await get_anime_base_positive()
            if self.nsfw_level > 0:
                base_positive = base_positive.replace("general, ", "")
            prompt_parts.append(base_positive)
            negative_parts.append(await get_anime_base_negative())

        nsfw_levels = await get_nsfw_levels()

        for field_name, _ in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            if value == "":
                continue

            if field_name == "nsfw_level":
                # For levels 4-5, try model-type-specific prompts (anime/real)
                if value >= 4 and build_as_type in ("anime", "real"):
                    try:
                        type_prompt = await get_prompt(f"nsfw_level_{value}_{build_as_type}")
                        type_neg = await get_prompt(f"nsfw_level_{value}_{build_as_type}_neg")
                        prompt_parts.append(type_prompt)
                        negative_parts.append(type_neg)
                    except KeyError:
                        nsfw_level = nsfw_levels[value]
                        prompt_parts.append(nsfw_level.prompt)
                        negative_parts.append(nsfw_level.negative_prompt)
                else:
                    nsfw_level = nsfw_levels[value]
                    prompt_parts.append(nsfw_level.prompt)
                    negative_parts.append(nsfw_level.negative_prompt)
                continue

            prompt_parts.append(value)
        prompt = ", ".join(prompt_parts)
        negative_prompt = ", ".join(negative_parts)

        return prompt, negative_prompt
