import logging

import replicate
import fal_client

from shared.services.prompt_service import get_prompt
from ..schemas.generate import ImageSize, get_anime_base_positive, get_anime_base_negative


def truncate_prompt(prompt: str, max_tokens: int = 75) -> str:
    parts = [p.strip() for p in prompt.split(",") if p.strip()]
    result = []
    current_tokens = 0

    for part in parts:
        part_tokens = len(part.split())
        if current_tokens + part_tokens <= max_tokens:
            result.append(part)
            current_tokens += part_tokens
        else:
            break

    return ", ".join(result) if result else prompt[:300]


async def submit_real(
        prompt: str,
        allow_nsfw: bool,
        nsfw_level: int = 0,
        image_size: ImageSize = ImageSize(width=1024, height=1024)
) -> str | None:
    handler = await fal_client.submit_async(
        "fal-ai/z-image/turbo",
        arguments={
            "prompt": prompt,
            "enable_safety_checker": not allow_nsfw,
            "image_size": image_size.model_dump(),
        }
    )

    result = await handler.get()
    logging.info(f"FAL result (nsfw_level={nsfw_level}): {result}")

    if result and "images" in result and result["images"]:
        return result["images"][0]["url"]
    return None


async def submit_anime(
    positive_prompt: str,
    negative_prompt: str,
    model_version: str = "aisha-ai-official/wai-nsfw-illustrious-v12:0fc0fa9885b284901a6f9c0b4d67701fd7647d157b88371427d63f8089ce140e"
):
    # positive_prompt = truncate_prompt(positive_prompt, max_tokens=75)
    # negative_prompt = truncate_prompt(negative_prompt, max_tokens=75)

    result = await replicate.async_run(
        model_version,
        input={
            "prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "vae": "default",
            "seed": -1,
            "cfg_scale": 5,
            "pag_scale": 5,
            "scheduler": "Euler a",
            "prepend_preprompt": False
        }
    )

    return result[0].url

age_interval_by_age = {  
    "18": "18-20 years old",
    "25": "20-30 years old",
    "35": "30-40 years old",
    "45": "50 years old",
    "70": "60-70 years old"
}
skin_by_age = {
    "18": "smooth youthful skin",
    "25": "smooth skin",
    "35": "clear mature skin, refined features",
    "45": "mature skin, elegant features",
    "70": "mature skin with character, distinguished features"
}

nsfw_level_to_prompt_real = [  
    "and she is fully covered in clothes",
    "seducing and teasing with her posture",
    "making accent on her beautiful ass and tits",
    "but she lowering it to show her naked tits", 
    "but she pulled her pants down to the floor to show her (naked tits) and (naked ass and shaved pussy)",  
    "showing her naked tits and beautiful naked ass",  
]

body_type_to_prompt = {
    "anorexic slender body": "very thin slender figure, narrow hips and visible collarbones",
    "petite slim body": "petite slender figure and slim waist",
    "fit body": "slim athletic build, toned figure and fit physique",
    "curvy body": "curvy hourglass figure, wide hips and soft curves",
    "fat body": "plus size figure, full bodied and thick curves"
}


async def build_prompt_from_character(
        character: dict,
        face_expression: str,
        location: str,
        position: str,
        outfit_key: str,
        nsfw_level: int,
        close_up: bool = False
) -> tuple[str, str]:
    logging.info(f"{character=}")
    logging.info(f"{outfit_key=}")
    pos, neg = "", ""
    default_outfit = character["visual"].get("default_outfit") or character["visual"].get('wardrobe', {}).get("casual")
    outfit = character["visual"]["wardrobe"].get(outfit_key) or default_outfit
    if character["model_type"] == "real":
        logging.info(f"{outfit=}")
        if nsfw_level and outfit_key != "nude":
            nsfw_modificator = f", {nsfw_level_to_prompt_real[nsfw_level]}"
            if nsfw_level in [4, 5]:
                position += "and touching herself between legs, wet spot on her crotch, watered pussy"
        else:
            nsfw_modificator = ""
        template = await get_prompt("z_image_template")
        pos = template.format(
            **character["visual"],
            face_expression=face_expression,
            age_interval=age_interval_by_age[character["visual"]["age"]],
            location=location,
            position=position,
            skin=skin_by_age[character["visual"]["age"]],
            outfit=outfit,
            nsfw_modificator=nsfw_modificator,
            shot_distance="close up" if close_up else "full-body"
        )
        neg = ""  # empty for z-image-turbo
    elif character["model_type"] == "anime":
        template = await get_prompt("illustrious_template")
        neg = await get_anime_base_negative()
        pos = template.format(
            **character["visual"],
            face_expression=face_expression,
            age_interval=age_interval_by_age[character["visual"]["age"]],
            location=location,
            position=position,
            skin=skin_by_age[character["visual"]["age"]],
            outfit=outfit,
            nsfw_modificator=None,  # тут не нужен
            shot_distance="close up" if close_up else "full-body"
        )
        pos += ", general"

    return pos, neg
