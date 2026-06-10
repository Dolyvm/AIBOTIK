import enum
import hashlib
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel
from shared.services.prompt_service import get_prompt
from shared.services.cache import get_cache

class ModelType(enum.Enum):
    real = "real"
    anime = "anime"
    manhwa = "manhwa"

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

async def get_manhwa_base_positive() -> str:
    from shared.services.workflows.manhwa_illustrious import MANHWA_BASE_POSITIVE
    try:
        return await get_prompt("manhwa_base_positive")
    except KeyError:
        return MANHWA_BASE_POSITIVE

async def get_manhwa_base_negative() -> str:
    from shared.services.workflows.manhwa_illustrious import MANHWA_BASE_NEGATIVE
    try:
        return await get_prompt("manhwa_base_negative")
    except KeyError:
        return MANHWA_BASE_NEGATIVE

async def get_real_base_positive(gender: str = "female") -> str:
    key = "real_base_positive_male" if gender == "male" else "real_base_positive_female"
    try:
        return await get_prompt(key)
    except KeyError:
        return await get_prompt("real_base_positive")

async def get_real_base_negative(gender: str = "female") -> str:
    key = "real_base_negative_male" if gender == "male" else "real_base_negative_female"
    try:
        return await get_prompt(key)
    except KeyError:
        return await get_prompt("real_base_negative")

REAL_PHOTO_QUALITY_PROMPT = (
    "RAW photo, anatomically correct adult human body, proportional limbs, natural face, "
    "realistic facial features, sharp eyes, realistic skin texture, high detail editorial photography"
)

REAL_ARTIFACT_NEGATIVE_PROMPT = (
    "worst quality, low quality, blurry, jpeg artifacts, watermark, text, logo, cropped, "
    "out of frame, deformed face, distorted face, asymmetrical face, poorly drawn face, "
    "cloned face, bad eyes, cross-eyed, deformed eyes, bad teeth, bad hands, deformed hands, "
    "malformed hands, mutated hands, extra fingers, missing fingers, fused fingers, too many fingers, "
    "bad legs, deformed legs, malformed legs, bad feet, deformed feet, extra limbs, missing limbs, "
    "broken anatomy, dislocated joints, twisted limbs, bad proportions, long neck, cgi, 3d render, "
    "cartoon, anime, illustration, painting, doll, plastic skin, waxy skin, oversmoothed skin"
)

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

REAL_ANIME_ONLY_TAGS = {"1girl", "1boy", "anime girl", "anime boy"}

REAL_FACE_SHAPES = [
    "oval face",
    "heart-shaped face",
    "soft square face",
    "long elegant face",
    "diamond face shape",
    "round soft face",
]

REAL_NOSE_DETAILS = [
    "straight narrow nose",
    "soft rounded nose",
    "defined bridge nose",
    "small upturned nose",
    "slender aquiline nose",
    "natural broad nose",
]

REAL_MOUTH_DETAILS = [
    "full lips",
    "soft bow-shaped lips",
    "wide expressive mouth",
    "small delicate lips",
    "defined cupid bow",
    "natural relaxed lips",
]

REAL_EYE_DETAILS = [
    "wide-set eyes",
    "almond-shaped eyes",
    "deep-set eyes",
    "slightly hooded eyes",
    "large expressive eyes",
    "narrow elegant eyes",
]

REAL_BROW_DETAILS = [
    "soft arched eyebrows",
    "straight natural eyebrows",
    "thick defined eyebrows",
    "delicate lifted eyebrows",
    "low expressive eyebrows",
    "clean shaped eyebrows",
]

REAL_FEMALE_BODY_VARIANTS = [
    "slim hourglass figure",
    "toned athletic curves",
    "petite fit figure",
    "proportional elegant build",
    "curvy fit silhouette",
    "lean dancer-like body",
]

REAL_MALE_BODY_VARIANTS = [
    "broad-shouldered athletic build",
    "lean muscular build",
    "defined v-shaped torso",
    "tall fit physique",
    "compact powerful build",
    "sculpted muscular body",
]

REAL_BREAST_VARIANTS = [
    "round perky breasts",
    "teardrop-shaped natural breasts",
    "high-set firm breasts",
    "soft full breasts",
    "wide-set natural breasts",
    "compact rounded breasts",
]

REAL_NIPPLE_VARIANTS = [
    "small raised nipples",
    "medium rosy nipples",
    "prominent erect nipples",
    "small dark areolas",
    "soft pink areolas",
    "natural asymmetric areolas",
]

BODY_PROFILE_PHRASES = {
    "female": {
        "body_type": {
            "slim": "slim natural build",
            "athletic": "toned athletic build",
            "proportional": "proportional feminine build",
            "soft_curvy": "soft curvy hourglass body",
            "large": "larger full-figured build",
        },
        "height": {
            "short": "short stature",
            "average": "average height",
            "tall": "tall stature",
        },
        "breast_size": {
            "small": "small natural breasts",
            "medium": "medium natural breasts",
            "large": "large natural breasts",
            "very_large": "very large breasts, prominent bust",
        },
        "butt_size": {
            "compact": "compact hips and butt",
            "medium": "medium hips and butt",
            "rounded": "rounded hips and butt",
            "large": "wide rounded hips, full butt",
        },
    },
    "male": {
        "body_type": {
            "lean": "lean masculine build",
            "athletic": "athletic masculine build",
            "muscular": "muscular build",
            "broad": "broad-shouldered build",
            "large": "large sturdy build",
        },
        "height": {
            "short": "short stature",
            "average": "average height",
            "tall": "tall stature",
        },
    },
}

OUTFIT_PRESET_PHRASES = {
    "casual": (
        "fully clothed casual everyday outfit, opaque fitted cotton top, "
        "straight-leg jeans, simple sneakers"
    ),
    "elegant": (
        "fully clothed elegant outfit, tailored long-sleeve blouse or shirt, "
        "high-waisted trousers or knee-length skirt, polished shoes"
    ),
    "sporty": (
        "fully clothed sporty activewear, opaque athletic zip top or fitted t-shirt, "
        "high-waisted leggings or joggers, clean sneakers"
    ),
    "home": (
        "fully clothed comfortable homewear, soft opaque long-sleeve lounge top, "
        "loose lounge pants, cozy socks"
    ),
}

CLOTHED_VISUAL_GUARD = (
    "fully clothed, visible opaque outfit, modest covered styling, "
    "covered chest torso and hips, clothing clearly visible"
)


def _stable_choice(seed: str, salt: str, options: list[str]) -> str:
    digest = hashlib.md5(f"{seed}:{salt}".encode()).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _strip_real_anime_tags(text: str) -> str:
    parts = []
    for part in text.split(","):
        tag = part.strip()
        if tag.lower() not in REAL_ANIME_ONLY_TAGS:
            parts.append(tag)
    return ", ".join(part for part in parts if part)


def _dedupe_comma_tags(parts: list[str]) -> list[str]:
    tags = []
    seen = set()
    for part in parts:
        for tag in part.split(","):
            tag_stripped = tag.strip()
            normalized = tag_stripped.lower()
            if tag_stripped and normalized not in seen:
                seen.add(normalized)
                tags.append(tag_stripped)
    return tags


def _build_real_identity_signature(
    character: dict,
    visual: dict,
    is_male: bool,
    nsfw_level: int,
    has_body_description: bool,
) -> str:
    seed = "|".join(
        filter(
            None,
            [
                str(character.get("id", "")),
                str(character.get("name", "")),
                str(visual.get("nationality", "")),
                str(visual.get("hair_color", "")),
                str(visual.get("eye_color", "")),
            ],
        )
    ) or "default-real-character"

    parts = [
        _stable_choice(seed, "face", REAL_FACE_SHAPES),
        _stable_choice(seed, "nose", REAL_NOSE_DETAILS),
        _stable_choice(seed, "mouth", REAL_MOUTH_DETAILS),
        _stable_choice(seed, "eyes", REAL_EYE_DETAILS),
        _stable_choice(seed, "brows", REAL_BROW_DETAILS),
        "distinct individual face",
    ]

    nationality = visual.get("nationality")
    if nationality:
        parts.append(f"individualized {nationality} facial features")

    if nsfw_level >= 2 and not has_body_description:
        if is_male:
            parts.append(_stable_choice(seed, "male-body", REAL_MALE_BODY_VARIANTS))
        else:
            parts.append(_stable_choice(seed, "female-body", REAL_FEMALE_BODY_VARIANTS))
            if nsfw_level >= 3:
                parts.append(_stable_choice(seed, "breasts", REAL_BREAST_VARIANTS))
                parts.append(_stable_choice(seed, "nipples", REAL_NIPPLE_VARIANTS))

    return ", ".join(parts)


REAL_SFW_RISKY_TAG_REPLACEMENTS = {
    "alluring": "confident",
    "seductive": "confident",
    "sensual": "expressive",
}


def _sanitize_real_sfw_tag(tag: str) -> str:
    words = tag.split()
    sanitized = [REAL_SFW_RISKY_TAG_REPLACEMENTS.get(word.lower(), word) for word in words]
    return " ".join(sanitized)


def _sanitize_real_sfw_prompt(prompt: str) -> str:
    return ", ".join(
        filter(
            None,
            (_sanitize_real_sfw_tag(tag.strip()) for tag in prompt.split(",")),
        )
    )


def _build_body_profile_phrase(body_profile: dict, gender: str) -> str:
    if not isinstance(body_profile, dict):
        body_profile = {}
    mappings = BODY_PROFILE_PHRASES["male" if gender == "male" else "female"]
    parts = []
    for key in ("body_type", "height", "breast_size", "butt_size"):
        value = body_profile.get(key)
        phrase = mappings.get(key, {}).get(value)
        if phrase:
            parts.append(phrase)
    return ", ".join(parts)


def _build_clothed_body_profile_phrase(body_profile: dict, gender: str) -> str:
    if not isinstance(body_profile, dict):
        body_profile = {}

    if gender == "male":
        body_type_map = {
            "lean": "lean clothed silhouette",
            "athletic": "athletic clothed silhouette",
            "muscular": "muscular clothed silhouette",
            "broad": "broad-shouldered clothed silhouette",
            "large": "large sturdy clothed silhouette",
        }
    else:
        body_type_map = {
            "slim": "slim clothed silhouette",
            "athletic": "toned athletic clothed silhouette",
            "proportional": "proportional feminine clothed silhouette",
            "soft_curvy": "soft curvy hourglass clothed silhouette",
            "large": "larger full-figured clothed silhouette",
        }

    height_map = BODY_PROFILE_PHRASES["male" if gender == "male" else "female"].get("height", {})
    upper_map = {
        "small": "modest upper-body proportions under clothing",
        "medium": "balanced upper-body proportions under clothing",
        "large": "full upper-body proportions under clothing",
        "very_large": "very full upper-body proportions under clothing",
    }
    lower_map = {
        "compact": "compact lower-body curves under clothing",
        "medium": "balanced lower-body curves under clothing",
        "rounded": "rounded lower-body curves under clothing",
        "large": "full lower-body curves under clothing",
    }

    parts = []
    for value, mapping in (
        (body_profile.get("body_type"), body_type_map),
        (body_profile.get("height"), height_map),
        (body_profile.get("breast_size"), upper_map),
        (body_profile.get("butt_size"), lower_map),
    ):
        phrase = mapping.get(value)
        if phrase:
            parts.append(phrase)
    return ", ".join(parts)


def _outfit_from_body_profile(body_profile: dict) -> str:
    if not isinstance(body_profile, dict):
        return ""
    return OUTFIT_PRESET_PHRASES.get(body_profile.get("outfit_preset", ""), "")


def _build_identity_reference_prompt(visual: dict, gender: str, nsfw_level: int = 0) -> str:
    identity_reference = visual.get("identity_reference") or {}
    if identity_reference.get("status") != "ready":
        return ""

    parts = [identity_reference.get("identity_prompt", "")]
    visible_traits = identity_reference.get("visible_traits")
    if isinstance(visible_traits, dict):
        for value in visible_traits.values():
            if value and str(value).strip().lower() != "uncertain":
                parts.append(str(value))
    if nsfw_level <= 2:
        body_phrase = _build_clothed_body_profile_phrase(visual.get("body_profile") or {}, gender)
    else:
        body_phrase = _build_body_profile_phrase(visual.get("body_profile") or {}, gender)
    if body_phrase:
        parts.append(body_phrase)
    return ", ".join(_dedupe_comma_tags([part for part in parts if part]))


class Prompt(BaseModel):
    character_base: Optional[str] = ""
    signature: Optional[str] = ""
    clothing_guard: Optional[str] = ""
    body_silhouette: Optional[str] = ""
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
        gender = visual.get("gender", "female")
        is_male = gender == "male"

        wardrobe = visual.get("wardrobe", {})
        if outfit_key == "default_outfit":
            clothing = (
                visual.get("default_outfit", "")
                or wardrobe.get("casual", "")
                or _outfit_from_body_profile(visual.get("body_profile") or {})
            )
        elif outfit_key == "nude" and nsfw_level >= 4 and not wardrobe.get("nude"):
            clothing = "nothing, fully nude" if is_male else "nothing, fully nude, bare skin"
        elif outfit_key == "underwear" and nsfw_level >= 2 and not wardrobe.get("underwear"):
            clothing = "underwear" if is_male else "bra and panties"
        else:
            clothing = wardrobe.get(outfit_key, visual.get("default_outfit", "") or wardrobe.get("casual", ""))
        if clothing:
            clothing = clothing.strip().rstrip('",').rstrip('"').strip()

        appearance = visual.get("appearance", character.get("appearance", ""))
        # Defensive: strip trailing quotes/commas from user-pasted data
        if appearance:
            appearance = appearance.strip().rstrip('",').rstrip('"').strip()

        # Если appearance пуст - строим из отдельных полей (пользовательские персонажи)
        if not appearance and visual.get("age"):
            if model_type in ("anime", "manhwa"):
                if is_male:
                    parts = ["1boy", "anime boy"]
                else:
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
                if is_male:
                    if visual.get("build"):
                        parts.append(visual["build"])
                    if visual.get("facial_hair"):
                        parts.append(visual["facial_hair"])
                else:
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
                    parts.append(f"{nationality} {'man' if is_male else 'woman'}")
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
                    if is_male:
                        parts.append(f"{visual['eye_color']} eyes")
                    else:
                        parts.append(f"beautiful {visual['eye_color']} eyes")
                if visual.get("body_type"):
                    parts.append(visual["body_type"])
                if is_male:
                    if visual.get("build"):
                        parts.append(visual["build"])
                    if visual.get("facial_hair"):
                        parts.append(visual["facial_hair"])
                else:
                    if visual.get("boobs"):
                        parts.append(f"with {visual['boobs']}")
                    if visual.get("ass"):
                        parts.append(f"and {visual['ass']}")
                appearance = ", ".join(parts)

        body = visual.get("body", "")
        face = visual.get("face", "")
        style = visual.get("style_tags", "")

        identity_character_base = ""
        if model_type == "real" and visual.get("custom_avatar"):
            identity_character_base = _build_identity_reference_prompt(visual, gender, nsfw_level)
        body_silhouette = ""
        if model_type == "real" and visual.get("custom_avatar"):
            if nsfw_level <= 2:
                body_phrase = _build_clothed_body_profile_phrase(visual.get("body_profile") or {}, gender)
            else:
                body_phrase = _build_body_profile_phrase(visual.get("body_profile") or {}, gender)
            if body_phrase:
                body_silhouette = f"body silhouette: {body_phrase}"
        clothing_guard = ""
        if nsfw_level <= 2:
            clothing_guard = CLOTHED_VISUAL_GUARD
            if clothing:
                clothing_guard = f"{clothing_guard}, wearing {clothing}"

        if model_type in ("anime", "manhwa"):
            character_base = ", ".join(filter(None, [appearance, body, face]))
        elif identity_character_base:
            character_base = identity_character_base
            character_base = _strip_real_anime_tags(character_base)
        else:
            character_base = ", ".join(filter(None, [appearance, body, face]))
            character_base = _strip_real_anime_tags(character_base)
            character_base = ", ".join(
                filter(
                    None,
                    [
                        character_base,
                        _build_real_identity_signature(
                            character,
                            visual,
                            is_male,
                            nsfw_level,
                            has_body_description=bool(body.strip()),
                        ),
                    ],
                )
            )

        # Принудительно добавить гендерный тег в начало, если его нет
        cb_lower = character_base.lower()
        if model_type in ("anime", "manhwa"):
            if is_male and "1boy" not in cb_lower:
                character_base = "1boy, " + character_base
            elif not is_male and "1girl" not in cb_lower:
                character_base = "1girl, " + character_base
        else:
            gender_prefix = (
                "single adult man, anatomically male"
                if is_male
                else "single adult woman, anatomically female"
            )
            if not character_base.lower().startswith(gender_prefix):
                character_base = f"{gender_prefix}, {character_base}"

        return cls(
            character_base=character_base,
            clothing_guard=clothing_guard,
            body_silhouette=body_silhouette,
            clothing=clothing,
            style=style,
            environment=environment,
            nsfw_level=nsfw_level
        )

    async def build_prompt(self, build_as_type: ModelType = None, gender: str = "female") -> tuple[str, str]:
        if isinstance(build_as_type, ModelType):
            build_as_type = build_as_type.value
        prompt_parts = []
        negative_parts = []
        base_positive = ""
        quality_positive = ""

        if build_as_type == "anime":
            base_positive = await get_anime_base_positive()
            if self.nsfw_level > 0:
                base_positive = base_positive.replace("general, ", "")
            negative_parts.append(await get_anime_base_negative())
        elif build_as_type == "manhwa":
            base_positive = await get_manhwa_base_positive()
            negative_parts.append(await get_manhwa_base_negative())
        elif build_as_type == "real":
            base_positive = await get_real_base_positive(gender)
            negative_parts.append(await get_real_base_negative(gender))
            quality_positive = REAL_PHOTO_QUALITY_PROMPT
            negative_parts.append(REAL_ARTIFACT_NEGATIVE_PROMPT)
        nsfw_levels = await get_nsfw_levels()

        async def append_nsfw_layer(raw_value) -> None:
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                value = 0
            value = max(0, min(value, len(nsfw_levels) - 1))

            resolved = False
            if value >= 2:
                type_key = build_as_type if build_as_type in ("anime", "real", "manhwa") else None
                # Priority: model_type+gender specific → generic fallback.
                lookup_keys = []
                if type_key:
                    if type_key == "real" and gender == "female":
                        lookup_keys.append(f"nsfw_level_{value}_real_female")
                    elif gender == "male":
                        lookup_keys.append(f"nsfw_level_{value}_{type_key}_male")
                    lookup_keys.append(f"nsfw_level_{value}_{type_key}")
                if gender == "male":
                    lookup_keys.append(f"nsfw_level_{value}_male")

                for key in lookup_keys:
                    try:
                        type_prompt = await get_prompt(key)
                        type_neg = await get_prompt(f"{key}_neg")
                        prompt_parts.append(type_prompt)
                        negative_parts.append(type_neg)
                        resolved = True
                        break
                    except KeyError:
                        continue

            if not resolved:
                nsfw_level = nsfw_levels[value]
                prompt_parts.append(nsfw_level.prompt)
                negative_parts.append(nsfw_level.negative_prompt)

        priority_fields = [
            "character_base",
            "signature",
            "clothing_guard",
            "body_silhouette",
            "clothing",
            "body_state",
            "action",
            "facial_expression",
            "environment",
            "scene_details",
            "camera",
            "style",
            "nsfw_level",
        ]
        seen_fields = set()

        for field_name in priority_fields:
            seen_fields.add(field_name)
            if field_name == "nsfw_level":
                await append_nsfw_layer(getattr(self, field_name))
                continue

            value = getattr(self, field_name)
            if value in ("", None):
                continue
            prompt_parts.append(value)

        if base_positive:
            prompt_parts.append(base_positive)
        if quality_positive:
            prompt_parts.append(quality_positive)

        for field_name, _ in self.__class__.model_fields.items():
            if field_name in seen_fields:
                continue
            value = getattr(self, field_name)
            if value in ("", None):
                continue
            prompt_parts.append(value)

        # Гендерные ограничения в negative_prompt
        if gender == "male":
            negative_parts.append("female, breasts, 1girl, woman")
        else:
            negative_parts.append("1boy, male, penis")

        prompt = ", ".join(_dedupe_comma_tags(prompt_parts))
        if build_as_type == "real" and self.nsfw_level < 2:
            prompt = _sanitize_real_sfw_prompt(prompt)
        negative_prompt = ", ".join(_dedupe_comma_tags(negative_parts))

        return prompt, negative_prompt
