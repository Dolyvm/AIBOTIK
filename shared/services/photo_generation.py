import json
import logging
import re
import ssl
import uuid
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

import httpcore
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import (
    IMAGES_STORAGE_PATH,
    REPLICATE_API_TOKEN,
    REPLICATE_POLL_INTERVAL_SECONDS,
    REPLICATE_POLL_TIMEOUT_SECONDS,
    STRUCTURED_MODEL,
)
from shared.models import Chat, GeneratedImage, Message, User
from shared.services.llm import LLMClient
from shared.services.prompt_service import get_prompt

logger = logging.getLogger(__name__)

REAL_MODEL = "prunaai/z-image-turbo"
ANIME_MODEL_VERSION = (
    "aisha-ai-official/animagine-xl-v4-opt:"
    "cfd0f86fbcd03df45fca7ce83af9bb9c07850a3317303fe8dcf677038541db8a"
)
REPLICATE_OUTPUT_DOWNLOAD_ATTEMPTS = 3

PROMPT_BUDGETS = {
    "real": 450,
    "anime": 100,
}
ANIME_NEGATIVE_BUDGET = 50

ANIME_FILLER_TAGS = {
    "anime illustration",
    "detailed background",
    "detailed face",
    "high quality",
    "best quality",
}
ANIME_EXPLICIT_RATING_TAGS = "explicit, nsfw"
ANIME_SAFE_RATING_TAGS = "safe"
ANIME_EXPLICIT_DETAIL_TAGS_BY_GENDER = {
    "female": "uncensored, visible pussy, detailed vulva, visible labia",
    "male": "uncensored, visible penis, detailed penis, visible testicles",
}
ANIME_QUALITY_TAGS = "masterpiece, high score, great score, absurdres"
ANIME_TAG_LIMITS = {
    "identity": (4, 5, 36),
    "appearance": (3, 3, 28),
    "body": (2, 3, 24),
    "face": (2, 3, 24),
    "clothing": (9, 5, 40),
    "pose": (1, 6, 36),
    "expression": (1, 3, 24),
    "emotion": (1, 2, 18),
    "setting": (2, 3, 22),
    "scene_notes": (2, 3, 24),
    "style_tags": (2, 3, 24),
    "rating_tags": (2, 2, 18),
    "explicit_detail_tags": (4, 3, 24),
    "quality_tags": (4, 2, 18),
}


class PhotoGenerationError(Exception):
    pass


class UnsupportedPhotoModelError(PhotoGenerationError):
    pass


class PhotoPromptBudgetError(PhotoGenerationError):
    pass


class PhotoProviderError(PhotoGenerationError):
    pass


class PhotoGenerationCanceled(PhotoGenerationError):
    pass


@dataclass(slots=True)
class PhotoPromptBundle:
    model_type: str
    gender: str
    prompt: str
    negative_prompt: str | None
    scene: dict[str, Any]
    replicate_input: dict[str, Any]
    replicate_model: str
    state_meta_update: dict[str, Any] | None = None


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


STRUCTURAL_APPEARANCE_TAGS = {
    "solo",
    "1boy",
    "1girl",
    "anime boy",
    "anime girl",
    "anime style",
}
MALE_MATURE_HINT_PATTERN = re.compile(
    r"\b(man|male|mature|muscular|beard|mustache|facial hair|stubble|[2-9][0-9]\s*(?:years?\s*old|yo|y/o))\b",
    flags=re.IGNORECASE,
)

OUTFIT_ACTIONS = {"none", "default", "wardrobe", "custom"}
REAL_DEFAULT_OUTFIT_WARDROBE_PRIORITY = (
    "casual",
    "formal",
    "business",
    "office",
    "everyday",
    "sleepwear",
    "gym",
)
GENERIC_REAL_DEFAULT_OUTFIT = "casual modern outfit"
EXPOSURE_PATTERN = re.compile(
    r"\b("
    r"expos(?:e|es|ed|ing)\s+(?:genitals?|pussy|vagina|crotch)|"
    r"genitals?\s+(?:visible|exposed)|"
    r"pussy\s+(?:visible|exposed)|"
    r"show(?:ing)?\s+(?:her\s+)?(?:pussy|genitals?|vagina)|"
    r"spread(?:ing)?\s+legs?\s+(?:wide\s+)?to\s+expose|"
    r"naked|nude"
    r")\b",
    re.IGNORECASE,
)
REAL_REVEALING_OUTFIT_PATTERN = re.compile(
    r"\b("
    r"naked|nude|nothing|topless|shirtless|"
    r"underwear|lingerie|bra|panties|panty|thong|"
    r"bikini|swimwear|swimsuit|"
    r"bare\s+(?:breasts?|chest|genitals?)|"
    r"show(?:ing)?\s+(?:her\s+|his\s+)?(?:pussy|genitals?|vagina|penis|breasts?)"
    r")\b",
    re.IGNORECASE,
)
REAL_CLOTHED_PATTERN = re.compile(r"\b(?:fully\s+clothed|clothed|dressed)\b", re.IGNORECASE)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value)).strip()


def _split_csv_items(value: Any, max_items: int | None = None) -> list[str]:
    items: list[str] = []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    for raw_value in values:
        for raw_item in re.split(r"[,;\n]+", _clean_text(raw_value)):
            item = _clean_text(raw_item).strip(" ,")
            if not item:
                continue
            items.append(item)
            if max_items is not None and len(items) >= max_items:
                return items
    return items


def _dedupe_items(
    raw_items: Iterable[str],
    seen: set[str] | None = None,
    max_items: int = 60,
) -> list[str]:
    seen = seen if seen is not None else set()
    items: list[str] = []
    for item in raw_items:
        item = _clean_text(item).strip(" ,")
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def _dedupe_csv(text: Any, max_items: int = 60) -> str:
    items = _dedupe_items(_split_csv_items(text), max_items=max_items)
    return ", ".join(items)


def _normalize_anime_tag(item: str) -> str:
    item = _clean_text(item).strip(" ,")
    if not item:
        return ""
    lowered = item.lower()
    if lowered in ANIME_FILLER_TAGS:
        return ""
    return item


def _truncate_tag(item: str, max_words: int, max_chars: int) -> str:
    item = _normalize_anime_tag(item)
    if not item:
        return ""

    words = item.split()
    if len(words) > max_words:
        item = " ".join(words[:max_words])
    if len(item) > max_chars:
        item = item[:max_chars].rsplit(" ", 1)[0] or item[:max_chars]
    return item.strip(" ,")


def _compact_csv_tags(
    value: Any,
    max_items: int,
    max_words: int,
    max_chars: int,
) -> str:
    items = (
        _truncate_tag(item, max_words=max_words, max_chars=max_chars)
        for item in _split_csv_items(value)
    )
    return ", ".join(_dedupe_items(items, max_items=max_items))


def _compact_anime_context(context: Mapping[str, Any]) -> dict[str, Any]:
    compact = dict(context)
    for field, (max_items, max_words, max_chars) in ANIME_TAG_LIMITS.items():
        compact[field] = _compact_csv_tags(
            compact.get(field),
            max_items=max_items,
            max_words=max_words,
            max_chars=max_chars,
        )
    return compact


def _strip_anime_filler_tags(text: str) -> str:
    return ", ".join(
        _dedupe_items((_normalize_anime_tag(item) for item in _split_csv_items(text)), max_items=200)
    )


def _estimate_prompt_tokens(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", text or ""))


def _render_template(template: str, context: Mapping[str, Any]) -> str:
    rendered = template.format_map(_SafeFormatDict({k: _clean_text(v) for k, v in context.items()}))
    rendered = re.sub(r"\s+", " ", rendered).strip(" ,")
    return _dedupe_csv(rendered, 200)


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return fields


def _fit_prompt_budget(
    template: str,
    context: dict[str, Any],
    budget: int,
    removable_fields: Sequence[str],
    label: str,
    log_meta: Mapping[str, Any] | None = None,
) -> str:
    original_context = dict(context)
    active_context = dict(original_context)
    original_prompt = _render_template(template, active_context)
    original_tokens = _estimate_prompt_tokens(original_prompt)
    if original_tokens <= budget:
        return original_prompt

    logger.warning(
        "Photo prompt before trimming: label=%s budget=%s tokens=%s meta=%s\n"
        "TEMPLATE:\n%s\nORIGINAL_CONTEXT:\n%s\nORIGINAL_PROMPT:\n%s",
        label,
        budget,
        original_tokens,
        json.dumps(dict(log_meta or {}), ensure_ascii=False, default=str),
        template,
        json.dumps(original_context, ensure_ascii=False, default=str),
        original_prompt,
    )

    prompt = original_prompt

    fields = _template_fields(template)
    removed_fields: list[str] = []
    for field in removable_fields:
        if field not in fields:
            continue
        active_context[field] = ""
        removed_fields.append(field)
        prompt = _render_template(template, active_context)
        if _estimate_prompt_tokens(prompt) <= budget:
            return prompt

    logger.warning(
        "Photo prompt budget exceeded: label=%s budget=%s tokens=%s removed_fields=%s meta=%s\n"
        "TEMPLATE:\n%s\nTRIMMED_CONTEXT:\n%s\nTRIMMED_PROMPT:\n%s",
        label,
        budget,
        _estimate_prompt_tokens(prompt),
        removed_fields,
        json.dumps(dict(log_meta or {}), ensure_ascii=False, default=str),
        template,
        json.dumps(active_context, ensure_ascii=False, default=str),
        prompt,
    )
    raise PhotoPromptBudgetError(f"{label} prompt is too long after removing optional blocks")


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise PhotoGenerationError("LLM did not return a JSON object")
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise PhotoGenerationError("LLM scene response must be a JSON object")
    return data


def _normalize_model_type(character: Mapping[str, Any]) -> str:
    visual = _character_visual(character)
    model_type = _clean_text(character.get("model_type") or visual.get("model_type") or "anime").lower()
    if model_type == "manhva":
        model_type = "manhwa"
    if model_type == "manhwa":
        raise UnsupportedPhotoModelError("Генерация фото для manhwa пока не поддерживается")
    if model_type not in {"anime", "real"}:
        raise UnsupportedPhotoModelError(f"Генерация фото для типа '{model_type}' не поддерживается")
    return model_type


def _normalize_gender(character: Mapping[str, Any]) -> str:
    visual = _character_visual(character)
    gender = _clean_text(visual.get("gender") or character.get("gender") or "female").lower()
    return gender if gender in {"male", "female"} else "female"


def _character_visual(character: Mapping[str, Any]) -> dict[str, Any]:
    visual_data = character.get("visual_data") or {}
    visual = character.get("visual") or {}
    merged: dict[str, Any] = {}
    if isinstance(visual_data, Mapping):
        merged.update(visual_data)
    if isinstance(visual, Mapping):
        merged.update(visual)
    return merged


def _visual_field_tag(key: str, value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if key == "hair_color" and not re.search(r"\b(hair|bald)\b", text, re.IGNORECASE):
        return f"{text} hair"
    if key == "eye_color" and not re.search(r"\beyes?\b", text, re.IGNORECASE):
        return f"{text} eyes"
    if key == "skin" and not re.search(r"\bskin\b", text, re.IGNORECASE):
        return f"{text} skin"
    return text


def _visual_parts(character: Mapping[str, Any]) -> dict[str, str]:
    visual = _character_visual(character)

    body_keys = (
        "body",
        "body_type",
        "build",
        "age",
        "height",
        "weight",
        "ass",
        "boobs",
        "breasts",
        "figure",
    )
    face_keys = (
        "face",
        "hair_color",
        "haircut",
        "hair_style",
        "eye_color",
        "eyes",
        "skin",
        "facial_hair",
    )

    appearance_items = [
        item
        for item in _split_csv_items(character.get("appearance") or visual.get("appearance"))
        if item.lower() not in STRUCTURAL_APPEARANCE_TAGS
    ]
    body_items = [
        item
        for key in body_keys
        for item in _split_csv_items(_visual_field_tag(key, visual.get(key)))
    ]
    face_items = [
        item
        for key in face_keys
        for item in _split_csv_items(_visual_field_tag(key, visual.get(key)))
    ]
    style_items = _split_csv_items(visual.get("style_tags"))

    seen: set[str] = set()
    appearance = ", ".join(_dedupe_items(appearance_items, seen, 80))
    body = ", ".join(_dedupe_items(body_items, seen, 50))
    face = ", ".join(_dedupe_items(face_items, seen, 50))
    style_tags = ", ".join(_dedupe_items(style_items, seen, 30))

    return {
        "subject_tags": _anime_subject_tags(character),
        "identity": _visual_identity(character),
        "appearance": appearance,
        "body": body,
        "face": face,
        "default_outfit": _dedupe_csv(_clean_text(visual.get("default_outfit")), 40),
        "style_tags": style_tags,
    }


def _anime_subject_tags(character: Mapping[str, Any]) -> str:
    gender = _normalize_gender(character)
    if gender == "female":
        return "1girl, solo"

    visual = _character_visual(character)
    tags = ["1boy", "solo", "male focus"]
    hint_text = " ".join(
        _clean_text(value)
        for value in (
            character.get("appearance"),
            character.get("body"),
            visual.get("appearance"),
            visual.get("body"),
            visual.get("body_type"),
            visual.get("build"),
            visual.get("age"),
            visual.get("facial_hair"),
        )
    )
    if MALE_MATURE_HINT_PATTERN.search(hint_text):
        tags.append("mature male")
    return ", ".join(tags)


def _visual_identity(character: Mapping[str, Any]) -> str:
    visual = _character_visual(character)

    identity_keys = (
        "hair_color",
        "haircut",
        "hair_style",
        "hair_length",
        "eye_color",
        "eyes",
        "skin",
    )

    def identity_item(item: str) -> str:
        item = _clean_text(item)
        tip_match = re.fullmatch(
            r"(black|brown|dark brown|blonde|blond|red|orange|blue|dark blue|purple|pink|white|silver|green)\s+tips",
            item,
            flags=re.IGNORECASE,
        )
        if tip_match:
            return f"{tip_match.group(1).lower()}-tipped hair ends"
        return item

    appearance_items = [
        identity_item(item)
        for item in _split_csv_items(character.get("appearance") or visual.get("appearance"))
        if item.lower() not in STRUCTURAL_APPEARANCE_TAGS
        and re.search(
            r"\b(hair|eyes?|skin|bald|ponytails?|twin tails?|braids?|bangs|bob|bun|tips)\b",
            item,
            flags=re.IGNORECASE,
        )
    ]
    structured_items = [
        identity_item(item)
        for key in identity_keys
        for item in _split_csv_items(_visual_field_tag(key, visual.get(key)))
    ]

    return ", ".join(_dedupe_items([*appearance_items, *structured_items], max_items=20))


def _wardrobe(character: Mapping[str, Any]) -> dict[str, str]:
    visual = _character_visual(character)
    wardrobe = visual.get("wardrobe") or {}
    if not isinstance(wardrobe, dict):
        return {}
    return {str(key): _clean_text(value) for key, value in wardrobe.items() if _clean_text(value)}


def _avatar_generation_character(character: Mapping[str, Any]) -> dict[str, Any]:
    avatar_character = dict(character)
    visual = dict(_character_visual(character))
    raw_model_type = _clean_text(
        character.get("model_type") or visual.get("model_type") or "anime"
    ).lower()
    if raw_model_type == "manhva":
        raw_model_type = "manhwa"

    if raw_model_type == "manhwa":
        raw_model_type = "anime"
        visual["style_tags"] = _dedupe_csv(
            [visual.get("style_tags"), "manhwa style, webtoon style, clean line art"],
            30,
        )

    visual["model_type"] = raw_model_type
    avatar_character["model_type"] = raw_model_type
    avatar_character["visual_data"] = visual
    avatar_character["visual"] = {
        **(character.get("visual") if isinstance(character.get("visual"), Mapping) else {}),
        **visual,
    }
    return avatar_character


def _avatar_clothing_prompt(
    model_type: str,
    gender: str,
    visual: Mapping[str, str],
    wardrobe: Mapping[str, str],
) -> str:
    if model_type == "real":
        return _real_clothing_prompt(
            _real_default_photo_outfit(visual["default_outfit"], wardrobe)
        )
    return _dedupe_csv(visual["default_outfit"], 40) or "casual outfit"


def _stored_photo_outfit(chat_state: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(chat_state, Mapping):
        return {}
    outfit = chat_state.get("photo_outfit")
    if not isinstance(outfit, Mapping):
        return {}

    source = _clean_text(outfit.get("source"))
    clothing = _clean_text(outfit.get("clothing"))
    if source not in {"default", "wardrobe", "custom"} or not clothing:
        return {}

    return {
        "source": source,
        "wardrobe_key": _clean_text(outfit.get("wardrobe_key")),
        "clothing": clothing,
    }


def _photo_outfit_update(source: str, clothing: str, wardrobe_key: str = "") -> dict[str, Any]:
    return {
        "photo_outfit": {
            "source": source,
            "wardrobe_key": wardrobe_key,
            "clothing": clothing,
        }
    }


def _photo_state_payload(
    visual: Mapping[str, Any],
    wardrobe: Mapping[str, str],
    chat_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    current_outfit = _stored_photo_outfit(chat_state)
    return {
        "current_outfit": current_outfit,
        "default_outfit": _dedupe_csv(_clean_text(visual.get("default_outfit")), 40),
        "wardrobe": dict(wardrobe),
    }


def _find_wardrobe_key(wardrobe_key: str, wardrobe: Mapping[str, str]) -> str:
    if wardrobe_key in wardrobe:
        return wardrobe_key
    lowered_key = wardrobe_key.lower()
    for key in wardrobe:
        if key.lower() == lowered_key:
            return key
    return ""


def _scene_implies_exposure(scene: Mapping[str, Any]) -> bool:
    scene_text = " ".join(
        _clean_text(scene.get(key))
        for key in ("pose", "setting", "scene_notes", "expression", "emotion", "clothing")
    )
    clothing_items = {item.lower() for item in _split_csv_items(scene.get("clothing"))}
    return bool(
        EXPOSURE_PATTERN.search(scene_text)
        or clothing_items.intersection({"nothing", "nude", "naked", "no clothes"})
    )


def _anime_exposure_rating_tags(scene: Mapping[str, Any], clothing: str) -> str:
    return (
        ANIME_EXPLICIT_RATING_TAGS
        if _scene_implies_exposure({**dict(scene), "clothing": clothing})
        else ANIME_SAFE_RATING_TAGS
    )


def _anime_scene_notes_for_rating(scene_notes: Any, rating_tags: str) -> str:
    scene_notes = _clean_text(scene_notes)
    if rating_tags != ANIME_EXPLICIT_RATING_TAGS:
        return scene_notes

    adjusted_items: list[str] = []
    has_visible_body_framing = False
    for item in _split_csv_items(scene_notes):
        lowered = item.lower()
        if lowered in {"full body", "cowboy shot"}:
            has_visible_body_framing = True
            adjusted_items.append(item)
            continue
        if re.search(r"\b(?:upper body|close[- ]?up|portrait|headshot|cropped)\b", lowered):
            continue
        adjusted_items.append(item)

    if not has_visible_body_framing:
        adjusted_items.insert(0, "cowboy shot")
    return ", ".join(_dedupe_items(adjusted_items, max_items=6))


SPREAD_LEGS_PATTERN = re.compile(
    r"\b(?:legs?\s+spread|spread(?:ing)?\s+legs?|open\s+legs?|legs?\s+apart)\b",
    re.IGNORECASE,
)


def _anime_pose_for_rating(pose: Any, rating_tags: str) -> str:
    pose_items = _split_csv_items(pose)
    if rating_tags != ANIME_EXPLICIT_RATING_TAGS or len(pose_items) <= 1:
        return _clean_text(pose)

    primary_pose = pose_items[0]
    has_spread_legs = any(SPREAD_LEGS_PATTERN.search(item) for item in pose_items)
    if has_spread_legs and not SPREAD_LEGS_PATTERN.search(primary_pose):
        primary_pose = f"{primary_pose} with legs spread"
    return primary_pose


def _is_real_revealing_outfit(text: str) -> bool:
    return bool(REAL_REVEALING_OUTFIT_PATTERN.search(_clean_text(text)))


def _real_default_photo_outfit(default_outfit: str, wardrobe: Mapping[str, str]) -> str:
    default_outfit = _dedupe_csv(default_outfit, 40)
    if default_outfit:
        return default_outfit

    for priority_key in REAL_DEFAULT_OUTFIT_WARDROBE_PRIORITY:
        wardrobe_key = _find_wardrobe_key(priority_key, wardrobe)
        if (
            wardrobe_key
            and not _is_real_revealing_outfit(wardrobe_key)
            and not _is_real_revealing_outfit(wardrobe[wardrobe_key])
        ):
            return _dedupe_csv(wardrobe[wardrobe_key], 40)

    for wardrobe_key, clothing in wardrobe.items():
        if not _is_real_revealing_outfit(wardrobe_key) and not _is_real_revealing_outfit(clothing):
            return _dedupe_csv(clothing, 40)

    return GENERIC_REAL_DEFAULT_OUTFIT


def _real_clothing_prompt(clothing: str) -> str:
    clothing = _dedupe_csv(clothing, 40) or GENERIC_REAL_DEFAULT_OUTFIT
    if _is_real_revealing_outfit(clothing) or REAL_CLOTHED_PATTERN.search(clothing):
        return clothing
    return f"fully clothed, {clothing}"


def _forced_exposure_wardrobe_key(wardrobe: Mapping[str, str]) -> str:
    return _find_wardrobe_key("nude", wardrobe) or _find_wardrobe_key("underwear", wardrobe)


def _resolve_photo_outfit(
    model_type: str,
    visual: Mapping[str, str],
    wardrobe: Mapping[str, str],
    scene: Mapping[str, Any],
    chat_state: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    if model_type == "real":
        default_outfit = _real_default_photo_outfit(visual["default_outfit"], wardrobe)
    else:
        default_outfit = visual["default_outfit"]
    stored_outfit = _stored_photo_outfit(chat_state)
    fallback_clothing = stored_outfit.get("clothing") or default_outfit

    action = _clean_text(scene.get("outfit_action")).lower()
    if action not in OUTFIT_ACTIONS:
        if _clean_text(scene.get("wardrobe_key")):
            action = "wardrobe"
        elif _clean_text(scene.get("custom_clothing")):
            action = "custom"
        else:
            action = "none"

    if action in {"none", "default"} and _scene_implies_exposure(scene):
        wardrobe_key = _forced_exposure_wardrobe_key(wardrobe)
        if wardrobe_key:
            clothing = _dedupe_csv(wardrobe[wardrobe_key], 40)
            update = _photo_outfit_update("wardrobe", clothing, wardrobe_key)
            return clothing, update, {
                "requested_action": action,
                "resolved_action": "wardrobe",
                "reason": "exposure_override",
                "stored_outfit": stored_outfit,
                "default_outfit": default_outfit,
                "resolved_clothing": clothing,
                "state_meta_update": update,
            }

    if action == "none":
        update = None
        if not stored_outfit and default_outfit:
            update = _photo_outfit_update("default", default_outfit)
        return fallback_clothing, update, {
            "requested_action": action,
            "resolved_action": stored_outfit.get("source") or "default",
            "reason": "locked_or_initial_default",
            "stored_outfit": stored_outfit,
            "default_outfit": default_outfit,
            "resolved_clothing": fallback_clothing,
            "state_meta_update": update,
        }

    if action == "default":
        update = _photo_outfit_update("default", default_outfit) if default_outfit else {"photo_outfit": None}
        return default_outfit, update, {
            "requested_action": action,
            "resolved_action": "default",
            "reason": "explicit_default",
            "stored_outfit": stored_outfit,
            "default_outfit": default_outfit,
            "resolved_clothing": default_outfit,
            "state_meta_update": update,
        }

    if action == "wardrobe":
        wardrobe_key = _find_wardrobe_key(_clean_text(scene.get("wardrobe_key")), wardrobe)
        if not wardrobe_key:
            logger.warning(
                "Photo outfit wardrobe action ignored: invalid wardrobe_key=%r",
                scene.get("wardrobe_key"),
            )
            return fallback_clothing, None, {
                "requested_action": action,
                "resolved_action": stored_outfit.get("source") or "default",
                "reason": "invalid_wardrobe_key",
                "stored_outfit": stored_outfit,
                "default_outfit": default_outfit,
                "resolved_clothing": fallback_clothing,
                "state_meta_update": None,
            }

        clothing = _dedupe_csv(wardrobe[wardrobe_key], 40)
        update = _photo_outfit_update("wardrobe", clothing, wardrobe_key)
        return clothing, update, {
            "requested_action": action,
            "resolved_action": "wardrobe",
            "reason": "explicit_wardrobe",
            "stored_outfit": stored_outfit,
            "default_outfit": default_outfit,
            "resolved_clothing": clothing,
            "state_meta_update": update,
        }

    custom_clothing = _dedupe_csv(scene.get("custom_clothing"), 40)
    if not custom_clothing:
        logger.warning("Photo outfit custom action ignored: empty custom_clothing")
        return fallback_clothing, None, {
            "requested_action": action,
            "resolved_action": stored_outfit.get("source") or "default",
            "reason": "empty_custom_clothing",
            "stored_outfit": stored_outfit,
            "default_outfit": default_outfit,
            "resolved_clothing": fallback_clothing,
            "state_meta_update": None,
        }

    update = _photo_outfit_update("custom", custom_clothing)
    return custom_clothing, update, {
        "requested_action": action,
        "resolved_action": "custom",
        "reason": "explicit_custom",
        "stored_outfit": stored_outfit,
        "default_outfit": default_outfit,
        "resolved_clothing": custom_clothing,
        "state_meta_update": update,
    }


def _message_payload(messages: Iterable[Message | Mapping[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for message in list(messages)[-5:]:
        if isinstance(message, Mapping):
            role = _clean_text(message.get("role"))
            content = _clean_text(message.get("content"))
        else:
            role_value = getattr(message, "role", "")
            role = getattr(role_value, "value", role_value)
            content = getattr(message, "content", "")
            role = _clean_text(role)
            content = _clean_text(content)
        if role and content:
            result.append({"role": role, "content": content})
    return result


def _normalize_scene(scene: Mapping[str, Any]) -> dict[str, Any]:
    outfit_action = _clean_text(scene.get("outfit_action")).lower()
    custom_clothing = _clean_text(scene.get("custom_clothing"))
    if outfit_action not in OUTFIT_ACTIONS:
        if _clean_text(scene.get("wardrobe_key")):
            outfit_action = "wardrobe"
        elif custom_clothing:
            outfit_action = "custom"
        else:
            outfit_action = "none"
    if outfit_action == "custom" and not custom_clothing:
        custom_clothing = _clean_text(scene.get("clothing"))

    return {
        "pose": _clean_text(scene.get("pose"))[:180],
        "expression": _clean_text(scene.get("expression") or scene.get("emotion"))[:160],
        "emotion": _clean_text(scene.get("emotion") or scene.get("expression"))[:120],
        "outfit_action": outfit_action[:40],
        "clothing": _clean_text(scene.get("clothing"))[:220],
        "wardrobe_key": _clean_text(scene.get("wardrobe_key"))[:80],
        "custom_clothing": custom_clothing[:220],
        "setting": _clean_text(scene.get("setting") or scene.get("environment"))[:180],
        "scene_notes": _clean_text(scene.get("scene_notes") or scene.get("details"))[:220],
    }


class ReplicateImageClient:
    base_url = "https://api.replicate.com/v1"

    def __init__(
        self,
        api_token: str | None = None,
        poll_timeout_seconds: int = REPLICATE_POLL_TIMEOUT_SECONDS,
        poll_interval_seconds: float = REPLICATE_POLL_INTERVAL_SECONDS,
    ):
        self.api_token = api_token or REPLICATE_API_TOKEN
        self.poll_timeout_seconds = poll_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._version_cache: dict[str, str] = {}
        if not self.api_token:
            logger.warning("REPLICATE_API_TOKEN is not set")

    def _headers(self) -> dict[str, str]:
        if not self.api_token:
            raise PhotoProviderError("REPLICATE_API_TOKEN is not configured")
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    async def run(self, model: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        headers["Prefer"] = "wait=60"
        headers["Cancel-After"] = f"{self.poll_timeout_seconds}s"

        async with httpx.AsyncClient(timeout=70) as client:
            version = await self._resolve_version(client, model, headers)
            payload = {"version": version, "input": input_payload}
            response = await client.post(f"{self.base_url}/predictions", headers=headers, json=payload)
            if response.status_code >= 400:
                raise PhotoProviderError(f"Replicate create failed: HTTP {response.status_code}")
            prediction = response.json()

        return await self._wait_for_prediction(prediction)

    async def _resolve_version(
        self,
        client: httpx.AsyncClient,
        model: str,
        headers: Mapping[str, str],
    ) -> str:
        if ":" in model:
            version = model.rsplit(":", 1)[1].strip()
            if re.fullmatch(r"[a-f0-9]{64}", version):
                return version
            return model
        if re.fullmatch(r"[a-f0-9]{64}", model):
            return model
        if "/" not in model:
            return model
        if model in self._version_cache:
            return self._version_cache[model]

        owner, name = model.split("/", 1)
        response = await client.get(f"{self.base_url}/models/{owner}/{name}", headers=headers)
        if response.status_code >= 400:
            raise PhotoProviderError(f"Replicate model lookup failed: HTTP {response.status_code}")
        data = response.json()
        version = ((data.get("latest_version") or {}).get("id") or "").strip()
        if not version:
            raise PhotoProviderError("Replicate model lookup did not include latest version")
        self._version_cache[model] = version
        return version

    async def _wait_for_prediction(self, prediction: dict[str, Any]) -> dict[str, Any]:
        status = prediction.get("status")
        if status == "succeeded":
            return prediction
        if status in {"failed", "canceled"}:
            raise PhotoProviderError(f"Replicate prediction {status}: {prediction.get('error')}")

        get_url = (prediction.get("urls") or {}).get("get")
        if not get_url:
            raise PhotoProviderError("Replicate prediction did not include polling URL")

        timeout = httpx.Timeout(20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            elapsed = 0.0
            while elapsed < self.poll_timeout_seconds:
                await _sleep(self.poll_interval_seconds)
                elapsed += self.poll_interval_seconds
                response = await client.get(get_url, headers=self._headers())
                if response.status_code >= 400:
                    raise PhotoProviderError(f"Replicate poll failed: HTTP {response.status_code}")
                prediction = response.json()
                status = prediction.get("status")
                if status == "succeeded":
                    return prediction
                if status in {"failed", "canceled"}:
                    raise PhotoProviderError(f"Replicate prediction {status}: {prediction.get('error')}")

        raise PhotoProviderError("Replicate prediction timed out")

    async def download_output(self, output: Any) -> tuple[bytes, str, str]:
        url = self._first_output_url(output)
        safe_url = self._safe_output_url(url)
        last_error: Exception | None = None

        for attempt in range(1, REPLICATE_OUTPUT_DOWNLOAD_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {self.api_token}"},
                    )
                if response.status_code >= 400:
                    raise PhotoProviderError(
                        f"Replicate output download failed: HTTP {response.status_code}"
                    )
                content_type = (
                    response.headers.get("Content-Type", "image/png")
                    .split(";", 1)[0]
                    .strip()
                )
                return response.content, content_type, url
            except PhotoProviderError:
                raise
            except (
                httpx.HTTPError,
                httpcore.NetworkError,
                httpcore.ProtocolError,
                httpcore.ProxyError,
                httpcore.TimeoutException,
                ssl.SSLError,
                OSError,
            ) as e:
                last_error = e
                if attempt >= REPLICATE_OUTPUT_DOWNLOAD_ATTEMPTS:
                    break
                logger.warning(
                    "Replicate output download failed; retrying: attempt=%s/%s url=%s error_type=%s",
                    attempt,
                    REPLICATE_OUTPUT_DOWNLOAD_ATTEMPTS,
                    safe_url,
                    type(e).__name__,
                )
                await _sleep(min(attempt, 2))

        error_type = type(last_error).__name__ if last_error else "unknown"
        raise PhotoProviderError(
            "Replicate output download failed after "
            f"{REPLICATE_OUTPUT_DOWNLOAD_ATTEMPTS} attempts: {error_type}"
        )

    @staticmethod
    def _safe_output_url(url: str) -> str:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return "<invalid-url>"
        return f"{parts.scheme}://{parts.netloc}{parts.path}"

    @staticmethod
    def _first_output_url(output: Any) -> str:
        if isinstance(output, str) and output:
            return output
        if isinstance(output, list):
            for item in output:
                if isinstance(item, str) and item:
                    return item
        raise PhotoProviderError("Replicate prediction did not return an image URL")


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


class PhotoGenerationService:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        replicate_client: ReplicateImageClient | None = None,
    ):
        self.llm_client = llm_client or LLMClient(
            model=STRUCTURED_MODEL,
            provider={"sort": "throughput"},
            reasoning={"enabled": False},
            max_retries=3,
        )
        self.replicate_client = replicate_client or ReplicateImageClient()

    async def build_scene(
        self,
        character: Mapping[str, Any],
        recent_messages: Sequence[Message | Mapping[str, Any]],
        chat_state: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_prompt = await get_prompt("photo_scene_extractor")
        model_type = _normalize_model_type(character)
        gender = _normalize_gender(character)
        visual_data = _character_visual(character)
        wardrobe = _wardrobe(character)

        payload = {
            "character": {
                "id": character.get("id"),
                "name": character.get("name"),
                "model_type": model_type,
                "gender": gender,
            },
            "photo_state": _photo_state_payload(visual_data, wardrobe, chat_state),
            "recent_messages": _message_payload(recent_messages),
        }

        response = await self.llm_client.generate(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            max_tokens=450,
            temperature=0.2,
            extra_payload={"response_format": {"type": "json_object"}},
        )
        return _normalize_scene(_extract_json_object(response.content))

    async def build_prompt_bundle(
        self,
        character: Mapping[str, Any],
        scene: Mapping[str, Any],
        chat_state: Mapping[str, Any] | None = None,
        log_meta: Mapping[str, Any] | None = None,
    ) -> PhotoPromptBundle:
        model_type = _normalize_model_type(character)
        gender = _normalize_gender(character)
        visual = _visual_parts(character)
        wardrobe = _wardrobe(character)

        clothing, state_meta_update, outfit_decision = _resolve_photo_outfit(
            model_type,
            visual,
            wardrobe,
            scene,
            chat_state,
        )
        logger.warning(
            "Photo scene/outfit decision: meta=%s scene=%s outfit_decision=%s",
            json.dumps(dict(log_meta or {}), ensure_ascii=False, default=str),
            json.dumps(dict(scene), ensure_ascii=False, default=str),
            json.dumps(outfit_decision, ensure_ascii=False, default=str),
        )
        clothing_prompt = (
            _real_clothing_prompt(clothing)
            if model_type == "real"
            else _dedupe_csv(clothing, 40)
        )
        rating_tags = ""
        explicit_detail_tags = ""
        quality_tags = ""
        pose = scene.get("pose", "")
        scene_notes = scene.get("scene_notes", "")
        if model_type == "anime":
            rating_tags = _anime_exposure_rating_tags(scene, clothing_prompt)
            explicit_detail_tags = (
                ANIME_EXPLICIT_DETAIL_TAGS_BY_GENDER.get(gender, "")
                if rating_tags == ANIME_EXPLICIT_RATING_TAGS
                else ""
            )
            quality_tags = ANIME_QUALITY_TAGS
            pose = _anime_pose_for_rating(pose, rating_tags)
            scene_notes = _anime_scene_notes_for_rating(scene_notes, rating_tags)

        context = {
            "character_name": character.get("name", ""),
            "gender": gender,
            "subject_tags": visual["subject_tags"],
            "identity": visual["identity"],
            "appearance": visual["appearance"],
            "body": visual["body"],
            "face": visual["face"],
            "clothing": clothing_prompt,
            "pose": pose,
            "expression": scene.get("expression", ""),
            "emotion": scene.get("emotion", ""),
            "setting": scene.get("setting", ""),
            "scene_notes": scene_notes,
            "style_tags": visual["style_tags"],
            "rating_tags": rating_tags,
            "explicit_detail_tags": explicit_detail_tags,
            "quality_tags": quality_tags,
        }
        if model_type == "anime":
            context = _compact_anime_context(context)

        template = await get_prompt(f"photo_prompt_{model_type}_{gender}")
        removable_fields = (
            ("style_tags", "scene_notes", "setting", "expression", "emotion", "body", "face", "appearance")
            if model_type == "anime"
            else ("scene_notes", "style_tags", "setting", "emotion")
        )
        prompt = _fit_prompt_budget(
            template,
            context,
            PROMPT_BUDGETS[model_type],
            removable_fields=removable_fields,
            label=f"{model_type}/{gender}",
            log_meta=log_meta,
        )
        if model_type == "anime":
            prompt = _strip_anime_filler_tags(prompt)

        negative_prompt = None
        if model_type == "anime":
            negative_template = await get_prompt(f"photo_negative_anime_{gender}")
            negative_prompt = _fit_prompt_budget(
                negative_template,
                context,
                ANIME_NEGATIVE_BUDGET,
                removable_fields=("scene_notes", "setting", "emotion", "style_tags"),
                label=f"anime/{gender} negative",
                log_meta=log_meta,
            )

        replicate_input = self._replicate_input(model_type, prompt, negative_prompt)
        replicate_model = ANIME_MODEL_VERSION if model_type == "anime" else REAL_MODEL
        return PhotoPromptBundle(
            model_type=model_type,
            gender=gender,
            prompt=prompt,
            negative_prompt=negative_prompt,
            scene=dict(scene),
            replicate_input=replicate_input,
            replicate_model=replicate_model,
            state_meta_update=state_meta_update,
        )

    async def build_avatar_prompt_bundle(
        self,
        character: Mapping[str, Any],
        log_meta: Mapping[str, Any] | None = None,
    ) -> PhotoPromptBundle:
        avatar_character = _avatar_generation_character(character)
        model_type = _normalize_model_type(avatar_character)
        gender = _normalize_gender(avatar_character)
        visual = _visual_parts(avatar_character)
        wardrobe = _wardrobe(avatar_character)
        clothing_prompt = _avatar_clothing_prompt(model_type, gender, visual, wardrobe)

        context = {
            "character_name": avatar_character.get("name", ""),
            "gender": gender,
            "subject_tags": visual["subject_tags"],
            "identity": visual["identity"],
            "appearance": visual["appearance"],
            "body": visual["body"],
            "face": visual["face"],
            "clothing": clothing_prompt,
            "pose": "upper body portrait, looking at viewer",
            "expression": "soft smile",
            "emotion": "calm",
            "setting": "simple clean background",
            "scene_notes": "profile avatar, centered composition, face clearly visible",
            "style_tags": visual["style_tags"],
            "rating_tags": ANIME_SAFE_RATING_TAGS if model_type == "anime" else "",
            "explicit_detail_tags": "",
            "quality_tags": ANIME_QUALITY_TAGS if model_type == "anime" else "",
        }
        if model_type == "anime":
            context = _compact_anime_context(context)

        template = await get_prompt(f"photo_prompt_{model_type}_{gender}")
        removable_fields = (
            ("style_tags", "scene_notes", "setting", "emotion", "body", "appearance")
            if model_type == "anime"
            else ("scene_notes", "style_tags", "setting", "emotion")
        )
        prompt = _fit_prompt_budget(
            template,
            context,
            PROMPT_BUDGETS[model_type],
            removable_fields=removable_fields,
            label=f"avatar/{model_type}/{gender}",
            log_meta=log_meta,
        )
        if model_type == "anime":
            prompt = _strip_anime_filler_tags(prompt)

        negative_prompt = None
        if model_type == "anime":
            negative_template = await get_prompt(f"photo_negative_anime_{gender}")
            negative_prompt = _fit_prompt_budget(
                negative_template,
                context,
                ANIME_NEGATIVE_BUDGET,
                removable_fields=("scene_notes", "setting", "emotion", "style_tags"),
                label=f"avatar/anime/{gender} negative",
                log_meta=log_meta,
            )

        replicate_input = self._replicate_input(model_type, prompt, negative_prompt)
        replicate_model = ANIME_MODEL_VERSION if model_type == "anime" else REAL_MODEL
        return PhotoPromptBundle(
            model_type=model_type,
            gender=gender,
            prompt=prompt,
            negative_prompt=negative_prompt,
            scene={
                "pose": context.get("pose", ""),
                "expression": context.get("expression", ""),
                "setting": context.get("setting", ""),
                "scene_notes": context.get("scene_notes", ""),
            },
            replicate_input=replicate_input,
            replicate_model=replicate_model,
        )

    @staticmethod
    def _replicate_input(
        model_type: str,
        prompt: str,
        negative_prompt: str | None,
    ) -> dict[str, Any]:
        if model_type == "real":
            return {
                "prompt": prompt,
                "width": 1024,
                "height": 1024,
                "num_inference_steps": 9,
                "guidance_scale": 0.0,
            }
        return {
            "prompt": prompt,
            "negative_prompt": negative_prompt or "",
            "cfg_scale": 5,
            "pag_scale": 5,
            "scheduler": "Euler a",
            "vae": "default",
            "width": 1024,
            "height": 1024,
            "batch_size": 1,
        }

    async def generate_for_chat(
        self,
        session: AsyncSession,
        user: User,
        chat_id: int,
        character: Mapping[str, Any],
        recent_messages: Sequence[Message | Mapping[str, Any]],
        chat_state: Mapping[str, Any] | None = None,
        before_save: Callable[[], Awaitable[None]] | None = None,
    ) -> GeneratedImage:
        if chat_state is None:
            chat = await session.get(Chat, chat_id)
            chat_state = dict(chat.state_meta or {}) if chat else {}

        scene = await self.build_scene(character, recent_messages, chat_state=chat_state)
        log_meta = {
            "chat_id": chat_id,
            "user_id": user.telegram_id,
            "character_id": character.get("id"),
        }
        bundle = await self.build_prompt_bundle(
            character,
            scene,
            chat_state=chat_state,
            log_meta=log_meta,
        )
        logger.warning(
            "Photo final prompt: chat_id=%s user_id=%s model_type=%s gender=%s "
            "positive_tokens=%s negative_tokens=%s\nPROMPT:\n%s\nNEGATIVE_PROMPT:\n%s",
            chat_id,
            user.telegram_id,
            bundle.model_type,
            bundle.gender,
            _estimate_prompt_tokens(bundle.prompt),
            _estimate_prompt_tokens(bundle.negative_prompt or ""),
            bundle.prompt,
            bundle.negative_prompt or "",
        )

        prediction = await self.replicate_client.run(bundle.replicate_model, bundle.replicate_input)
        image_bytes, content_type, provider_url = await self.replicate_client.download_output(
            prediction.get("output")
        )
        if before_save:
            await before_save()
        local_path = await self._save_image_bytes(image_bytes, content_type, user.telegram_id)
        if before_save:
            try:
                await before_save()
            except Exception:
                self._delete_saved_image(local_path)
                raise

        image = GeneratedImage(
            user_id=user.telegram_id,
            chat_id=chat_id,
            provider_url=provider_url,
            local_path=local_path,
            prompt=bundle.prompt,
            file_size=len(image_bytes),
            content_type=content_type,
        )
        await self._apply_state_meta_update(session, chat_id, bundle.state_meta_update)
        session.add(image)
        await session.commit()
        await session.refresh(image)
        logger.info(
            "Generated chat image: image_id=%s chat_id=%s model=%s provider_prediction=%s",
            image.id,
            chat_id,
            bundle.replicate_model,
            prediction.get("id"),
        )
        return image

    @staticmethod
    def _delete_saved_image(local_path: str) -> None:
        try:
            (Path(IMAGES_STORAGE_PATH) / local_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to delete canceled generated image file: %s", local_path)

    async def generate_avatar(self, character: Mapping[str, Any]) -> str:
        from shared.services.image_storage import save_avatar_image

        character_id = _clean_text(character.get("id")) or "character"
        log_meta = {
            "character_id": character_id,
            "purpose": "character_avatar",
        }
        bundle = await self.build_avatar_prompt_bundle(character, log_meta=log_meta)
        logger.warning(
            "Avatar final prompt: character_id=%s model_type=%s gender=%s "
            "positive_tokens=%s negative_tokens=%s\nPROMPT:\n%s\nNEGATIVE_PROMPT:\n%s",
            character_id,
            bundle.model_type,
            bundle.gender,
            _estimate_prompt_tokens(bundle.prompt),
            _estimate_prompt_tokens(bundle.negative_prompt or ""),
            bundle.prompt,
            bundle.negative_prompt or "",
        )

        prediction = await self.replicate_client.run(bundle.replicate_model, bundle.replicate_input)
        image_bytes, content_type, _provider_url = await self.replicate_client.download_output(
            prediction.get("output")
        )
        public_url = await save_avatar_image(image_bytes, content_type, character_id)
        logger.info(
            "Generated character avatar: character_id=%s model=%s provider_prediction=%s",
            character_id,
            bundle.replicate_model,
            prediction.get("id"),
        )
        return public_url

    @staticmethod
    async def _apply_state_meta_update(
        session: AsyncSession,
        chat_id: int,
        state_meta_update: Mapping[str, Any] | None,
    ) -> None:
        if not state_meta_update or "photo_outfit" not in state_meta_update:
            return

        chat = await session.get(Chat, chat_id)
        if not chat:
            logger.warning("Photo state update skipped: chat_id=%s not found", chat_id)
            return

        state_meta = dict(chat.state_meta or {})
        photo_outfit = state_meta_update.get("photo_outfit")
        if photo_outfit is None:
            state_meta.pop("photo_outfit", None)
        else:
            state_meta["photo_outfit"] = dict(photo_outfit)
        chat.state_meta = state_meta

    async def _save_image_bytes(self, image_bytes: bytes, content_type: str, user_id: int) -> str:
        import aiofiles

        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(content_type, ".png")
        user_dir = Path(IMAGES_STORAGE_PATH) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        full_path = user_dir / filename
        async with aiofiles.open(full_path, "wb") as file:
            await file.write(image_bytes)
        return f"{user_id}/{filename}"
