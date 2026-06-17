import base64
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
from shared.services import facefusion_provider, manhwa_provider
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
    "anime": 180,
    "manhwa": 180,
}
ANIME_PROMPT_PROFILE_VERSION = "anime_prompt_v2"
ANIME_AVATAR_PROMPT_BUDGET = 180
ANIME_NEGATIVE_BUDGET = 60

ANIME_TAG_LIMITS = {
    "body": (6, 5, 48),
    "face": (6, 5, 48),
    "clothing": (9, 5, 40),
    "pose": (4, 6, 36),
    "composition": (2, 3, 24),
    "expression": (1, 3, 24),
    "emotion": (1, 2, 18),
    "setting": (5, 5, 40),
    "style_tags": (4, 4, 32),
    "rating_tags": (2, 2, 18),
    "nudity_tags": (2, 2, 18),
    "focus_tags": (2, 2, 18),
    "quality_tags": (4, 2, 18),
}
ANIME_AVATAR_TAG_LIMITS = {
    **ANIME_TAG_LIMITS,
    "body": (6, 6, 56),
    "face": (5, 5, 48),
    "clothing": (8, 5, 48),
    "setting": (1, 3, 24),
    "scene_notes": (1, 3, 24),
    "style_tags": (2, 3, 24),
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
    provider: str = "replicate"
    state_meta_update: dict[str, Any] | None = None
    prompt_metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class AnimePromptComponent:
    field: str
    source: str
    tags: list[str]
    required: bool = False
    active: bool = True


@dataclass(slots=True)
class PhotoPromptPolicy:
    anime_filler_tags: set[str]
    anime_user_quality_tags: set[str]
    anime_rating_safe: str
    anime_rating_nsfw: str
    anime_rating_explicit: str
    anime_nudity_tags: str
    anime_focus_tags: str
    anime_quality_tags: str
    anime_avatar_quality_tags: str
    anime_subject_female: str
    anime_subject_male: str
    anime_negative_explicit: str
    avatar_scene: dict[str, str]
    avatar_default_outfit: str
    real_default_outfit: str
    real_clothed_prefix: str
    real_default_outfit_priority: tuple[str, ...]
    default_style_tags_real: str
    default_style_tags_anime: str
    default_style_tags_manhwa: str
    manhwa_style_tags: str
    default_wardrobe_female: dict[str, str]
    default_wardrobe_male: dict[str, str]


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


OUTFIT_ACTIONS = {"none", "default", "wardrobe", "custom"}
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
NUDITY_PATTERN = re.compile(
    r"\b(naked|nude|nudity|no\s+clothes|without\s+clothes|undressed|topless|shirtless)\b",
    re.IGNORECASE,
)
EXPLICIT_FOCUS_PATTERN = re.compile(
    r"\b("
    r"genital\s+focus|visible\s+genitals?|exposed\s+genitals?|"
    r"expos(?:e|es|ed|ing)\s+(?:genitals?|pussy|vagina|penis|crotch)|"
    r"(?:pussy|vagina|penis|genitals?)\s+(?:visible|exposed)|"
    r"show(?:ing)?\s+(?:her\s+|his\s+)?(?:pussy|vagina|penis|genitals?)"
    r")\b",
    re.IGNORECASE,
)
COMPOSITION_TAGS = {
    "full body",
    "cowboy shot",
    "upper body",
    "dynamic angle",
    "close-up",
    "close up",
    "portrait",
    "headshot",
}
GAZE_PATTERN = re.compile(r"\b(?:looking|gazing|staring)\b", re.IGNORECASE)
HANDS_PATTERN = re.compile(r"\b(?:hand|hands|arms?|fingers?)\b", re.IGNORECASE)
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


def _prompt_set(content: str) -> set[str]:
    return {_clean_text(item).lower() for item in _split_csv_items(content) if _clean_text(item)}


def _prompt_mapping(content: str, key: str) -> dict[str, str]:
    try:
        data = json.loads(content or "{}")
    except json.JSONDecodeError as e:
        raise PhotoGenerationError(f"Photo policy prompt '{key}' must be valid JSON") from e
    if not isinstance(data, Mapping):
        raise PhotoGenerationError(f"Photo policy prompt '{key}' must be a JSON object")
    return {str(k): _clean_text(v) for k, v in data.items() if _clean_text(v)}


async def get_photo_prompt_policy() -> PhotoPromptPolicy:
    async def prompt(key: str) -> str:
        return await get_prompt(key)

    avatar_scene = _prompt_mapping(await prompt("photo_policy_avatar_scene"), "photo_policy_avatar_scene")
    return PhotoPromptPolicy(
        anime_filler_tags=_prompt_set(await prompt("photo_policy_anime_filler_tags")),
        anime_user_quality_tags=_prompt_set(await prompt("photo_policy_anime_user_quality_tags")),
        anime_rating_safe=await prompt("photo_policy_anime_rating_safe"),
        anime_rating_nsfw=await prompt("photo_policy_anime_rating_nsfw"),
        anime_rating_explicit=await prompt("photo_policy_anime_rating_explicit"),
        anime_nudity_tags=await prompt("photo_policy_anime_nudity_tags"),
        anime_focus_tags=await prompt("photo_policy_anime_focus_tags"),
        anime_quality_tags=await prompt("photo_policy_anime_quality_tags"),
        anime_avatar_quality_tags=await prompt("photo_policy_anime_avatar_quality_tags"),
        anime_subject_female=await prompt("photo_policy_anime_subject_female"),
        anime_subject_male=await prompt("photo_policy_anime_subject_male"),
        anime_negative_explicit=await prompt("photo_policy_anime_negative_explicit"),
        avatar_scene={
            "pose": avatar_scene.get("pose", ""),
            "expression": avatar_scene.get("expression", ""),
            "composition": avatar_scene.get("composition", ""),
            "setting": avatar_scene.get("setting", ""),
            "exposure_intent": avatar_scene.get("exposure_intent", ""),
            "emotion": avatar_scene.get("emotion", ""),
            "scene_notes": avatar_scene.get("scene_notes", ""),
        },
        avatar_default_outfit=await prompt("photo_policy_avatar_default_outfit"),
        real_default_outfit=await prompt("photo_policy_real_default_outfit"),
        real_clothed_prefix=await prompt("photo_policy_real_clothed_prefix"),
        real_default_outfit_priority=tuple(
            _dedupe_items(_split_csv_items(await prompt("photo_policy_real_default_outfit_priority")), max_items=40)
        ),
        default_style_tags_real=await prompt("photo_policy_default_style_tags_real"),
        default_style_tags_anime=await prompt("photo_policy_default_style_tags_anime"),
        default_style_tags_manhwa=await prompt("photo_policy_default_style_tags_manhwa"),
        manhwa_style_tags=await prompt("photo_policy_manhwa_style_tags"),
        default_wardrobe_female=_prompt_mapping(
            await prompt("photo_policy_default_wardrobe_female"),
            "photo_policy_default_wardrobe_female",
        ),
        default_wardrobe_male=_prompt_mapping(
            await prompt("photo_policy_default_wardrobe_male"),
            "photo_policy_default_wardrobe_male",
        ),
    )


async def default_style_tags_for_model(model_type: str, raw_style_tags: str | None = None) -> str:
    if raw_style_tags and raw_style_tags.strip():
        return raw_style_tags
    policy = await get_photo_prompt_policy()
    if model_type == "real":
        return policy.default_style_tags_real
    if model_type == "manhwa":
        return policy.default_style_tags_manhwa
    return policy.default_style_tags_anime


async def apply_default_wardrobe(wardrobe: Mapping[str, Any], gender: str) -> dict[str, str]:
    policy = await get_photo_prompt_policy()
    result = {str(key): _clean_text(value) for key, value in dict(wardrobe or {}).items() if str(key).strip()}
    defaults = policy.default_wardrobe_male if gender == "male" else policy.default_wardrobe_female
    for key, value in defaults.items():
        result.setdefault(key, value)
    return result


def _normalize_anime_tag(item: str, policy: PhotoPromptPolicy) -> str:
    item = _clean_text(item).strip(" ,")
    if not item:
        return ""
    lowered = item.lower()
    if lowered in policy.anime_filler_tags:
        return ""
    return item


def _truncate_tag(item: str, max_words: int, max_chars: int, policy: PhotoPromptPolicy) -> str:
    item = _normalize_anime_tag(item, policy)
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
    policy: PhotoPromptPolicy,
) -> str:
    items = (
        _truncate_tag(item, max_words=max_words, max_chars=max_chars, policy=policy)
        for item in _split_csv_items(value)
    )
    return ", ".join(_dedupe_items(items, max_items=max_items))


def _compact_anime_context(context: Mapping[str, Any], policy: PhotoPromptPolicy) -> dict[str, Any]:
    compact = dict(context)
    for field, (max_items, max_words, max_chars) in ANIME_TAG_LIMITS.items():
        compact[field] = _compact_csv_tags(
            compact.get(field),
            max_items=max_items,
            max_words=max_words,
            max_chars=max_chars,
            policy=policy,
        )
    return compact


def _compact_anime_avatar_context(context: Mapping[str, Any], policy: PhotoPromptPolicy) -> dict[str, Any]:
    compact = dict(context)
    for field, (max_items, max_words, max_chars) in ANIME_AVATAR_TAG_LIMITS.items():
        compact[field] = _compact_csv_tags(
            compact.get(field),
            max_items=max_items,
            max_words=max_words,
            max_chars=max_chars,
            policy=policy,
        )
    return compact


def _strip_user_quality_tags(text: Any, policy: PhotoPromptPolicy) -> str:
    items = []
    for item in _split_csv_items(text):
        normalized = _clean_text(item).lower()
        if normalized in policy.anime_user_quality_tags or normalized in policy.anime_filler_tags:
            continue
        items.append(item)
    return ", ".join(_dedupe_items(items, max_items=80))


def _strip_anime_policy_final_tags(text: str, policy: PhotoPromptPolicy) -> str:
    final_remove_tags = {"adult"} if "adult" in policy.anime_filler_tags else set()
    return ", ".join(
        _dedupe_items(
            (
                item
                for item in _split_csv_items(text)
                if _clean_text(item).lower() not in final_remove_tags
            ),
            max_items=200,
        )
    )


def _estimate_prompt_tokens(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", text or ""))


def _render_template(template: str, context: Mapping[str, Any]) -> str:
    rendered = template.format_map(_SafeFormatDict({k: _clean_text(v) for k, v in context.items()}))
    rendered = re.sub(r"\s+", " ", rendered).strip(" ,")
    return _dedupe_csv(rendered, 200)


def _render_real_template(template: str, context: Mapping[str, Any]) -> str:
    rendered = template.format_map(_SafeFormatDict({k: _clean_text(v) for k, v in context.items()}))
    rendered = re.sub(r"\s+", " ", rendered).strip()
    rendered = re.sub(r"\s+([,.])", r"\1", rendered)
    rendered = re.sub(r"(?:\.\s*){2,}", ". ", rendered)
    rendered = re.sub(r"\s+,", ",", rendered)
    return rendered.strip(" ,")


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
    renderer: Callable[[str, Mapping[str, Any]], str] = _render_template,
) -> str:
    original_context = dict(context)
    active_context = dict(original_context)
    original_prompt = renderer(template, active_context)
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
        prompt = renderer(template, active_context)
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


def _trace_tag(
    trace: list[dict[str, str]],
    *,
    source: str,
    field: str,
    tag: str,
    action: str,
    reason: str,
) -> None:
    tag = _clean_text(tag)
    if not tag:
        return
    trace.append(
        {
            "source": source,
            "field": field,
            "tag": tag,
            "action": action,
            "reason": reason,
        }
    )


def _component(
    field: str,
    source: str,
    value: Any,
    *,
    required: bool = False,
) -> AnimePromptComponent | None:
    tags = _dedupe_items(_split_csv_items(value), max_items=200)
    if not tags:
        return None
    return AnimePromptComponent(field=field, source=source, tags=tags, required=required)


def _tag_override_items(overrides: Mapping[str, Any], key: str) -> list[str]:
    return _dedupe_items(_split_csv_items(overrides.get(key)), max_items=80)


def _visual_tag_overrides(character: Mapping[str, Any]) -> dict[str, list[str]]:
    visual = _character_visual(character)
    raw = visual.get("tag_overrides") or character.get("tag_overrides") or {}
    if not isinstance(raw, Mapping):
        return {
            "positive_add": [],
            "positive_remove": [],
            "negative_add": [],
            "negative_remove": [],
        }
    return {
        "positive_add": _tag_override_items(raw, "positive_add"),
        "positive_remove": _tag_override_items(raw, "positive_remove"),
        "negative_add": _tag_override_items(raw, "negative_add"),
        "negative_remove": _tag_override_items(raw, "negative_remove"),
    }


def _strip_component_filler(
    component: AnimePromptComponent,
    trace: list[dict[str, str]],
    policy: PhotoPromptPolicy,
) -> AnimePromptComponent | None:
    kept: list[str] = []
    for tag in component.tags:
        if component.field == "appearance" and _clean_text(tag).lower() != "adult":
            kept.append(tag)
            continue
        normalized = _normalize_anime_tag(tag, policy)
        if not normalized:
            _trace_tag(
                trace,
                source=component.source,
                field=component.field,
                tag=tag,
                action="drop",
                reason="filler",
            )
            continue
        kept.append(normalized)
    if not kept:
        return None
    component.tags = _dedupe_items(kept, max_items=200)
    return component


def _apply_tag_removals(
    components: list[AnimePromptComponent],
    remove_tags: Sequence[str],
    trace: list[dict[str, str]],
    reason: str,
) -> None:
    remove_set = {_clean_text(tag).lower() for tag in remove_tags if _clean_text(tag)}
    if not remove_set:
        return

    for component in components:
        kept: list[str] = []
        for tag in component.tags:
            if tag.lower() in remove_set:
                _trace_tag(
                    trace,
                    source=component.source,
                    field=component.field,
                    tag=tag,
                    action="drop",
                    reason=reason,
                )
                continue
            kept.append(tag)
        component.tags = kept


def _components_to_context(components: Sequence[AnimePromptComponent]) -> dict[str, str]:
    context: dict[str, str] = {}
    for component in components:
        if not component.active or not component.tags:
            continue
        context[component.field] = ", ".join(_dedupe_items(component.tags, max_items=200))

    context.setdefault("scene_notes", context.get("composition", ""))
    context.setdefault("nudity_tags", "")
    context.setdefault("focus_tags", "")
    context.setdefault("composition", "")
    return context


def _render_anime_prompt(
    template: str,
    components: Sequence[AnimePromptComponent],
    policy: PhotoPromptPolicy,
) -> str:
    prompt = _render_template(template, _components_to_context(components))
    return _strip_anime_policy_final_tags(prompt, policy)


def _fit_anime_components_to_budget(
    template: str,
    components: list[AnimePromptComponent],
    budget: int,
    trace: list[dict[str, str]],
    policy: PhotoPromptPolicy,
) -> str:
    drop_order = (
        "quality_tags",
        "style_tags",
        "setting",
        "composition",
        "expression",
        "face",
        "body",
    )
    prompt = _render_anime_prompt(template, components, policy)
    if _estimate_prompt_tokens(prompt) <= budget:
        return prompt

    for field in drop_order:
        dropped_any = False
        for component in components:
            if component.field != field or component.required or not component.active:
                continue
            component.active = False
            dropped_any = True
            for tag in component.tags:
                _trace_tag(
                    trace,
                    source=component.source,
                    field=component.field,
                    tag=tag,
                    action="drop",
                    reason="budget_component",
                )
        if not dropped_any:
            continue
        prompt = _render_anime_prompt(template, components, policy)
        if _estimate_prompt_tokens(prompt) <= budget:
            return prompt

    _trace_tag(
        trace,
        source="policy",
        field="prompt",
        tag=f"{_estimate_prompt_tokens(prompt)}/{budget}",
        action="keep",
        reason="budget_overflow_keep_required_tags",
    )
    return prompt


def _trace_kept_components(
    components: Sequence[AnimePromptComponent],
    trace: list[dict[str, str]],
) -> None:
    seen: set[str] = set()
    for component in components:
        if not component.active:
            continue
        for tag in component.tags:
            key = tag.lower()
            if key in seen:
                _trace_tag(
                    trace,
                    source=component.source,
                    field=component.field,
                    tag=tag,
                    action="drop",
                    reason="duplicate",
                )
                continue
            seen.add(key)
            _trace_tag(
                trace,
                source=component.source,
                field=component.field,
                tag=tag,
                action="keep",
                reason="selected",
            )


def _is_composition_tag(tag: str) -> bool:
    lowered = _clean_text(tag).lower()
    return lowered in COMPOSITION_TAGS or bool(
        re.search(r"\b(?:body|shot|portrait|headshot|close[- ]?up|angle)\b", lowered)
    )


def _is_gaze_tag(tag: str) -> bool:
    return bool(GAZE_PATTERN.search(_clean_text(tag)))


def _is_hands_tag(tag: str) -> bool:
    return bool(HANDS_PATTERN.search(_clean_text(tag)))


def _is_primary_pose_candidate(tag: str) -> bool:
    if not _clean_text(tag):
        return False
    return not (_is_composition_tag(tag) or _is_gaze_tag(tag) or _is_hands_tag(tag))


def _anime_scene_components(scene: Mapping[str, Any]) -> dict[str, str]:
    pose_items = _split_csv_items(
        [
            scene.get("primary_pose"),
            scene.get("pose"),
        ]
    )
    primary_pose = _clean_text(scene.get("primary_pose"))
    if not _is_primary_pose_candidate(primary_pose):
        primary_pose = ""
    if not primary_pose:
        for item in pose_items:
            if _is_primary_pose_candidate(item):
                primary_pose = item
                break

    modifier_items = _split_csv_items(scene.get("pose_modifiers"))
    for item in pose_items:
        if item == primary_pose or _is_composition_tag(item):
            continue
        if _is_gaze_tag(item) or _is_hands_tag(item) or not _is_primary_pose_candidate(item):
            modifier_items.append(item)
    for key in ("gaze", "hands"):
        modifier_items.extend(_split_csv_items(scene.get(key)))

    scene_note_items = _split_csv_items(scene.get("scene_notes"))
    composition_items = _split_csv_items(scene.get("composition"))
    for item in [*pose_items, *scene_note_items]:
        if _is_composition_tag(item):
            composition_items.append(item)

    place = _clean_text(scene.get("place") or scene.get("setting") or scene.get("environment"))
    setting_items = _split_csv_items(place)
    setting_items.extend(_split_csv_items(scene.get("background_objects")))
    setting_items.extend(_split_csv_items(scene.get("lighting")))
    for item in scene_note_items:
        if not _is_composition_tag(item):
            setting_items.append(item)

    return {
        "pose": ", ".join(_dedupe_items([primary_pose, *modifier_items], max_items=8)),
        "composition": ", ".join(_dedupe_items(composition_items, max_items=3)),
        "setting": ", ".join(_dedupe_items(setting_items, max_items=12)),
    }


def _anime_exposure_level(scene: Mapping[str, Any], clothing: str) -> str:
    intent = _clean_text(scene.get("exposure_intent")).lower().replace("-", "_").replace(" ", "_")
    if intent in {"explicit_focus", "genital_focus", "visible_genitals", "exposure"}:
        return "explicit_focus"
    if intent in {"nude", "naked", "nudity"}:
        return "nude"
    if intent in {"safe", "none", "sfw"}:
        return "safe"

    scene_text = " ".join(
        _clean_text(scene.get(key))
        for key in (
            "pose",
            "primary_pose",
            "pose_modifiers",
            "setting",
            "scene_notes",
            "composition",
            "expression",
            "emotion",
            "clothing",
            "place",
            "background_objects",
            "lighting",
        )
    )
    text = f"{scene_text} {clothing}"
    clothing_items = {item.lower() for item in _split_csv_items(clothing)}
    if EXPLICIT_FOCUS_PATTERN.search(text):
        return "explicit_focus"
    if NUDITY_PATTERN.search(text) or clothing_items.intersection(
        {"nothing", "nude", "naked", "no clothes"}
    ):
        return "nude"
    return "safe"


def _anime_rating_tags_for_level(level: str, policy: PhotoPromptPolicy) -> str:
    if level == "explicit_focus":
        return policy.anime_rating_explicit
    if level == "nude":
        return policy.anime_rating_nsfw
    return policy.anime_rating_safe


def _build_anime_prompt_result(
    *,
    character: Mapping[str, Any],
    gender: str,
    visual: Mapping[str, str],
    scene: Mapping[str, Any],
    clothing_prompt: str,
    template: str,
    negative_template: str,
    budget: int,
    negative_budget: int,
    purpose: str,
    log_meta: Mapping[str, Any] | None,
    policy: PhotoPromptPolicy,
    outfit_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    trace: list[dict[str, str]] = []
    exposure_level = _anime_exposure_level(scene, clothing_prompt)
    scene_parts = _anime_scene_components(scene)
    overrides = _visual_tag_overrides(character)

    raw_components = [
        _component("subject_tags", "policy", visual.get("subject_tags"), required=True),
        _component("appearance", "character.appearance", visual.get("appearance"), required=True),
        _component("body", "character.visual.body", visual.get("body")),
        _component("face", "character.visual.face", visual.get("face")),
        _component("clothing", "outfit", clothing_prompt, required=True),
        _component(
            "rating_tags",
            "policy",
            _anime_rating_tags_for_level(exposure_level, policy),
            required=True,
        ),
        _component(
            "nudity_tags",
            "policy",
            policy.anime_nudity_tags if exposure_level in {"nude", "explicit_focus"} else "",
            required=exposure_level in {"nude", "explicit_focus"},
        ),
        _component(
            "focus_tags",
            "policy",
            policy.anime_focus_tags if exposure_level == "explicit_focus" else "",
            required=exposure_level == "explicit_focus",
        ),
        _component("expression", "scene.expression", scene.get("expression")),
        _component("pose", "scene.pose", scene_parts.get("pose"), required=True),
        _component("composition", "scene.composition", scene_parts.get("composition")),
        _component("setting", "scene.setting", scene_parts.get("setting")),
        _component("style_tags", "character.visual.style_tags", visual.get("style_tags")),
        _component(
            "quality_tags",
            "policy",
            policy.anime_avatar_quality_tags if purpose == "avatar" else policy.anime_quality_tags,
        ),
    ]

    components = [
        cleaned
        for component in raw_components
        if component is not None
        for cleaned in [_strip_component_filler(component, trace, policy)]
        if cleaned is not None
    ]
    _apply_tag_removals(components, overrides["positive_remove"], trace, "override_remove")

    positive_add = _component("override_tags", "tag_overrides.positive_add", overrides["positive_add"])
    if positive_add:
        positive_add = _strip_component_filler(positive_add, trace, policy)
    if positive_add:
        components.append(positive_add)

    prompt = _fit_anime_components_to_budget(template, components, budget, trace, policy)
    _trace_kept_components(components, trace)

    negative_components = [
        _component("negative_base", "prompt.photo_negative", negative_template, required=True),
        _component(
            "negative_explicit",
            "policy",
            policy.anime_negative_explicit
            if exposure_level in {"nude", "explicit_focus"}
            else "",
        ),
    ]
    negative_components = [
        cleaned
        for component in negative_components
        if component is not None
        for cleaned in [_strip_component_filler(component, trace, policy)]
        if cleaned is not None
    ]
    _apply_tag_removals(
        negative_components,
        overrides["negative_remove"],
        trace,
        "override_remove",
    )
    negative_add = _component(
        "negative_override",
        "tag_overrides.negative_add",
        overrides["negative_add"],
    )
    if negative_add:
        negative_add = _strip_component_filler(negative_add, trace, policy)
    if negative_add:
        negative_components.append(negative_add)

    negative_prompt = _fit_anime_components_to_budget(
        "{negative_base}, {negative_explicit}, {negative_override}",
        negative_components,
        negative_budget,
        trace,
        policy,
    )
    _trace_kept_components(negative_components, trace)

    normalized_scene = {
        **dict(scene),
        "exposure_level": exposure_level,
        "pose": scene_parts.get("pose", ""),
        "composition": scene_parts.get("composition", ""),
        "setting": scene_parts.get("setting", ""),
    }
    metadata = {
        "profile_version": ANIME_PROMPT_PROFILE_VERSION,
        "purpose": purpose,
        "model_type": "anime",
        "gender": gender,
        "normalized_scene": normalized_scene,
        "outfit_decision": dict(outfit_decision or {}),
        "positive_prompt": prompt,
        "negative_prompt": negative_prompt,
        "positive_tokens": _estimate_prompt_tokens(prompt),
        "negative_tokens": _estimate_prompt_tokens(negative_prompt),
        "tag_trace": trace,
        "log_meta": dict(log_meta or {}),
    }
    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "metadata": metadata,
        "normalized_scene": normalized_scene,
    }


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
    if model_type not in {"anime", "real", "manhwa"}:
        raise UnsupportedPhotoModelError(f"Генерация фото для типа '{model_type}' не поддерживается")
    return model_type


def _normalize_gender(character: Mapping[str, Any]) -> str:
    visual = _character_visual(character)
    gender = _clean_text(visual.get("gender") or character.get("gender") or "female").lower()
    return gender if gender in {"male", "female"} else "female"


def _ensure_supported_model_gender(model_type: str, gender: str) -> None:
    if model_type == "manhwa" and gender != "male":
        raise UnsupportedPhotoModelError("Генерация manhwa доступна только для male characters")


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


def _identity_reference(visual: Mapping[str, Any]) -> dict[str, Any]:
    identity = visual.get("identity_reference")
    if not isinstance(identity, Mapping) or identity.get("status") != "ready":
        return {}
    return dict(identity)


def _identity_prompt_items(visual: Mapping[str, Any]) -> list[str]:
    identity = _identity_reference(visual)
    if not identity:
        return []
    items = _split_csv_items(identity.get("identity_prompt"))
    traits = identity.get("visible_traits")
    if isinstance(traits, Mapping):
        for key in ("hair", "skin", "eyes", "makeup", "accessories", "face_vibe"):
            value = _clean_text(traits.get(key))
            if value and value.lower() != "uncertain":
                items.extend(_split_csv_items(value))
    return _dedupe_items(items, max_items=20)


def _identity_source_image(character: Mapping[str, Any]) -> str:
    visual = _character_visual(character)
    if not visual.get("custom_avatar"):
        return ""
    identity = _identity_reference(visual)
    return _clean_text(identity.get("source_image") or visual.get("avatar"))


def _body_profile_items(visual: Mapping[str, Any]) -> list[str]:
    profile = visual.get("body_profile")
    if not isinstance(profile, Mapping):
        return []
    items = []
    body_type = _clean_text(profile.get("body_type")).replace("_", " ")
    height = _clean_text(profile.get("height"))
    breast_size = _clean_text(profile.get("breast_size")).replace("_", " ")
    butt_size = _clean_text(profile.get("butt_size")).replace("_", " ")
    if body_type:
        items.append(f"{body_type} body")
    if height:
        items.append(f"{height} height")
    if breast_size:
        items.append(f"{breast_size} breasts")
    if butt_size:
        items.append(f"{butt_size} hips")
    return items


def _outfit_from_body_profile(visual: Mapping[str, Any]) -> str:
    profile = visual.get("body_profile")
    if not isinstance(profile, Mapping):
        return ""
    preset = _clean_text(profile.get("outfit_preset")).lower()
    return {
        "casual": "casual modern outfit",
        "elegant": "elegant fitted outfit",
        "sporty": "sporty fitted outfit",
        "home": "comfortable home outfit",
    }.get(preset, "")


def _visual_parts(character: Mapping[str, Any], policy: PhotoPromptPolicy) -> dict[str, str]:
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

    appearance_items = _split_csv_items([character.get("appearance"), visual.get("appearance")])
    appearance_items.extend(_identity_prompt_items(visual))
    body_items = [
        item
        for key in body_keys
        for item in _split_csv_items(_visual_field_tag(key, visual.get(key)))
    ]
    body_items.extend(_body_profile_items(visual))
    face_items = [
        item
        for key in face_keys
        for item in _split_csv_items(_visual_field_tag(key, visual.get(key)))
    ]
    face_items.extend(_identity_prompt_items(visual))
    style_items = _split_csv_items(visual.get("style_tags"))

    appearance = ", ".join(_dedupe_items(appearance_items, max_items=200))
    body = ", ".join(_dedupe_items(body_items, max_items=80))
    face = ", ".join(_dedupe_items(face_items, max_items=80))
    style_tags = ", ".join(_dedupe_items(style_items, max_items=60))

    return {
        "subject_tags": _anime_subject_tags(character, policy),
        "appearance": appearance,
        "body": body,
        "face": face,
        "default_outfit": _dedupe_csv(
            [_clean_text(visual.get("default_outfit")), _outfit_from_body_profile(visual)],
            40,
        ),
        "style_tags": style_tags,
    }


def _anime_subject_tags(character: Mapping[str, Any], policy: PhotoPromptPolicy) -> str:
    gender = _normalize_gender(character)
    visual = _character_visual(character)
    appearance_tags = {
        item.lower()
        for item in _split_csv_items([character.get("appearance"), visual.get("appearance")])
    }

    tags: list[str] = []
    for tag in _split_csv_items(
        policy.anime_subject_female if gender == "female" else policy.anime_subject_male
    ):
        if tag.lower() not in appearance_tags:
            tags.append(tag)
    return ", ".join(tags)


def _wardrobe(character: Mapping[str, Any]) -> dict[str, str]:
    visual = _character_visual(character)
    wardrobe = visual.get("wardrobe") or {}
    if not isinstance(wardrobe, dict):
        return {}
    return {str(key): _clean_text(value) for key, value in wardrobe.items() if _clean_text(value)}


def _avatar_generation_character(
    character: Mapping[str, Any],
    policy: PhotoPromptPolicy,
) -> dict[str, Any]:
    avatar_character = dict(character)
    visual = dict(_character_visual(character))
    raw_model_type = _clean_text(
        character.get("model_type") or visual.get("model_type") or "anime"
    ).lower()
    if raw_model_type == "manhva":
        raw_model_type = "manhwa"

    if raw_model_type == "manhwa":
        visual["style_tags"] = _dedupe_csv(
            [visual.get("style_tags"), policy.manhwa_style_tags],
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
    policy: PhotoPromptPolicy,
) -> str:
    if model_type == "real":
        return _real_clothing_prompt(
            _real_default_photo_outfit(visual["default_outfit"], wardrobe, policy),
            policy,
        )
    return _dedupe_csv(visual["default_outfit"], 40) or _dedupe_csv(policy.avatar_default_outfit, 40)


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
        for key in (
            "pose",
            "primary_pose",
            "pose_modifiers",
            "setting",
            "scene_notes",
            "composition",
            "expression",
            "emotion",
            "clothing",
            "place",
            "background_objects",
            "lighting",
            "exposure_intent",
        )
    )
    clothing_items = {item.lower() for item in _split_csv_items(scene.get("clothing"))}
    return bool(
        EXPOSURE_PATTERN.search(scene_text)
        or clothing_items.intersection({"nothing", "nude", "naked", "no clothes"})
    )


def _anime_exposure_rating_tags(
    scene: Mapping[str, Any],
    clothing: str,
    policy: PhotoPromptPolicy,
) -> str:
    return (
        policy.anime_rating_explicit
        if _scene_implies_exposure({**dict(scene), "clothing": clothing})
        else policy.anime_rating_safe
    )


def _is_real_revealing_outfit(text: str) -> bool:
    return bool(REAL_REVEALING_OUTFIT_PATTERN.search(_clean_text(text)))


def _real_default_photo_outfit(
    default_outfit: str,
    wardrobe: Mapping[str, str],
    policy: PhotoPromptPolicy,
) -> str:
    default_outfit = _dedupe_csv(default_outfit, 40)
    if default_outfit:
        return default_outfit

    for priority_key in policy.real_default_outfit_priority:
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

    return _dedupe_csv(policy.real_default_outfit, 40)


def _real_clothing_prompt(clothing: str, policy: PhotoPromptPolicy) -> str:
    clothing = _dedupe_csv(clothing, 40) or _dedupe_csv(policy.real_default_outfit, 40)
    if _is_real_revealing_outfit(clothing) or REAL_CLOTHED_PATTERN.search(clothing):
        return clothing
    prefix = _dedupe_csv(policy.real_clothed_prefix, 10)
    return _dedupe_csv([prefix, clothing], 40)


def _forced_exposure_wardrobe_key(wardrobe: Mapping[str, str]) -> str:
    return _find_wardrobe_key("nude", wardrobe) or _find_wardrobe_key("underwear", wardrobe)


def _resolve_photo_outfit(
    model_type: str,
    visual: Mapping[str, str],
    wardrobe: Mapping[str, str],
    scene: Mapping[str, Any],
    chat_state: Mapping[str, Any] | None,
    policy: PhotoPromptPolicy,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    if model_type == "real":
        default_outfit = _real_default_photo_outfit(visual["default_outfit"], wardrobe, policy)
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


def _scene_extractor_prompt_key(model_type: str) -> str:
    if model_type == "real":
        return "photo_scene_extractor_real"
    if model_type == "manhwa":
        return "photo_scene_extractor_manhwa"
    return "photo_scene_extractor_anime"


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
        "scene_description": _clean_text(scene.get("scene_description"))[:600],
        "pose": _clean_text(scene.get("pose"))[:180],
        "primary_pose": _clean_text(scene.get("primary_pose"))[:120],
        "pose_modifiers": _dedupe_csv(scene.get("pose_modifiers"), 20)[:180],
        "gaze": _clean_text(scene.get("gaze"))[:80],
        "hands": _clean_text(scene.get("hands"))[:120],
        "composition": _clean_text(scene.get("composition"))[:120],
        "place": _clean_text(scene.get("place"))[:120],
        "background_objects": _dedupe_csv(scene.get("background_objects"), 20)[:180],
        "lighting": _clean_text(scene.get("lighting"))[:120],
        "exposure_intent": _clean_text(scene.get("exposure_intent"))[:80],
        "expression": _clean_text(scene.get("expression") or scene.get("emotion"))[:160],
        "emotion": _clean_text(scene.get("emotion") or scene.get("expression"))[:120],
        "outfit_action": outfit_action[:40],
        "clothing": _clean_text(scene.get("clothing"))[:220],
        "wardrobe_key": _clean_text(scene.get("wardrobe_key"))[:80],
        "custom_clothing": custom_clothing[:220],
        "setting": _clean_text(scene.get("setting") or scene.get("environment"))[:180],
        "scene_notes": _clean_text(scene.get("scene_notes") or scene.get("details"))[:220],
    }


def _real_scene_description(scene: Mapping[str, Any], gender: str) -> str:
    description = _clean_text(scene.get("scene_description"))
    if description:
        return description

    subject = "her" if gender == "female" else "him"
    composition = _clean_text(scene.get("composition")) or "full-body"
    pose = _dedupe_csv(
        [
            scene.get("primary_pose"),
            scene.get("pose"),
            scene.get("pose_modifiers"),
            scene.get("gaze"),
            scene.get("hands"),
        ],
        20,
    )
    setting = _dedupe_csv(
        [
            scene.get("place") or scene.get("setting"),
            scene.get("background_objects"),
            scene.get("lighting"),
            scene.get("scene_notes"),
        ],
        30,
    )

    first = f"A {composition} realistic photograph"
    if pose:
        first = f"{first} of {subject} {pose}"
    else:
        first = f"{first} of {subject}"
    if setting:
        return f"{first} in {setting}."
    return f"{first} with natural photographic framing."


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
        data_match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", url, flags=re.DOTALL)
        if data_match:
            try:
                content = base64.b64decode(
                    "".join(data_match.group(2).split()),
                    validate=True,
                )
            except Exception as e:
                raise PhotoProviderError("Image data URL decode failed") from e
            return content, data_match.group(1), ""

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


def _provider_prompt_metadata(
    *,
    provider: str,
    prompt: str,
    negative_prompt: str | None,
    replicate_input: Mapping[str, Any],
) -> dict[str, str | None]:
    if provider == "runpod_manhwa":
        provider_prompts = manhwa_provider.build_provider_prompts(prompt, negative_prompt or "")
        return {
            "provider_prompt": provider_prompts["positive_prompt"],
            "provider_negative_prompt": provider_prompts["negative_prompt"] or None,
        }

    return {
        "provider_prompt": _clean_text(replicate_input.get("prompt")),
        "provider_negative_prompt": _clean_text(replicate_input.get("negative_prompt")) or None,
    }


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
        model_type = _normalize_model_type(character)
        system_prompt = await get_prompt(_scene_extractor_prompt_key(model_type))
        gender = _normalize_gender(character)
        _ensure_supported_model_gender(model_type, gender)
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
        policy = await get_photo_prompt_policy()
        model_type = _normalize_model_type(character)
        gender = _normalize_gender(character)
        _ensure_supported_model_gender(model_type, gender)
        prompt_model_type = "anime" if model_type == "manhwa" else model_type
        visual = dict(_visual_parts(character, policy))
        prompt_character: Mapping[str, Any] = character
        if model_type == "manhwa":
            visual["style_tags"] = _dedupe_csv([visual.get("style_tags"), policy.manhwa_style_tags], 60)
            prompt_character = {
                **dict(character),
                "model_type": "anime",
                "visual_data": {
                    **_character_visual(character),
                    "model_type": "anime",
                    "style_tags": visual["style_tags"],
                },
            }
        wardrobe = _wardrobe(character)

        clothing, state_meta_update, outfit_decision = _resolve_photo_outfit(
            prompt_model_type,
            visual,
            wardrobe,
            scene,
            chat_state,
            policy,
        )
        logger.warning(
            "Photo scene/outfit decision: meta=%s scene=%s outfit_decision=%s",
            json.dumps(dict(log_meta or {}), ensure_ascii=False, default=str),
            json.dumps(dict(scene), ensure_ascii=False, default=str),
            json.dumps(outfit_decision, ensure_ascii=False, default=str),
        )
        clothing_prompt = (
            _real_clothing_prompt(clothing, policy)
            if prompt_model_type == "real"
            else _dedupe_csv(clothing, 40)
        )
        template_model_type = "manhwa" if model_type == "manhwa" else prompt_model_type
        template = await get_prompt(f"photo_prompt_{template_model_type}_{gender}")
        if prompt_model_type == "anime":
            negative_template = await get_prompt(f"photo_negative_{template_model_type}_{gender}")
            anime_result = _build_anime_prompt_result(
                character=prompt_character,
                gender=gender,
                visual=visual,
                scene=scene,
                clothing_prompt=clothing_prompt,
                template=template,
                negative_template=negative_template,
                budget=PROMPT_BUDGETS[model_type],
                negative_budget=ANIME_NEGATIVE_BUDGET,
                purpose="chat_photo",
                log_meta=log_meta,
                policy=policy,
                outfit_decision=outfit_decision,
            )
            prompt = anime_result["prompt"]
            negative_prompt = anime_result["negative_prompt"]
            replicate_input = self._replicate_input(prompt_model_type, prompt, negative_prompt)
            provider = "runpod_manhwa" if model_type == "manhwa" else "replicate"
            replicate_model = "runpod:manhwa" if model_type == "manhwa" else ANIME_MODEL_VERSION
            prompt_metadata = dict(anime_result["metadata"])
            prompt_metadata["model_type"] = model_type
            prompt_metadata["provider"] = provider
            prompt_metadata["replicate_input"] = dict(replicate_input)
            prompt_metadata["replicate_model"] = replicate_model
            prompt_metadata.update(
                _provider_prompt_metadata(
                    provider=provider,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    replicate_input=replicate_input,
                )
            )
            return PhotoPromptBundle(
                model_type=model_type,
                gender=gender,
                prompt=prompt,
                negative_prompt=negative_prompt,
                scene=dict(anime_result["normalized_scene"]),
                replicate_input=replicate_input,
                replicate_model=replicate_model,
                provider=provider,
                state_meta_update=state_meta_update,
                prompt_metadata=prompt_metadata,
            )

        exposure_level = _anime_exposure_level(scene, clothing_prompt)
        normalized_scene = {
            **dict(scene),
            "scene_description": _real_scene_description(scene, gender),
            "exposure_level": exposure_level,
        }

        context = {
            "character_name": character.get("name", ""),
            "gender": gender,
            "subject_tags": visual["subject_tags"],
            "appearance": visual["appearance"],
            "body": visual["body"],
            "face": visual["face"],
            "clothing": clothing_prompt,
            "scene_description": normalized_scene["scene_description"],
            "pose": scene.get("pose", ""),
            "expression": scene.get("expression", ""),
            "emotion": scene.get("emotion", ""),
            "setting": scene.get("setting", ""),
            "scene_notes": scene.get("scene_notes", ""),
            "style_tags": visual["style_tags"],
        }
        removable_fields = ("style_tags", "scene_notes", "setting", "emotion", "body", "face")
        prompt = _fit_prompt_budget(
            template,
            context,
            PROMPT_BUDGETS[model_type],
            removable_fields=removable_fields,
            label=f"{model_type}/{gender}",
            log_meta=log_meta,
            renderer=_render_real_template,
        )

        negative_prompt = None
        replicate_input = self._replicate_input(prompt_model_type, prompt, negative_prompt)
        replicate_model = ANIME_MODEL_VERSION if prompt_model_type == "anime" else REAL_MODEL
        prompt_metadata = {
            "profile_version": "real_prompt_v1",
            "purpose": "chat_photo",
            "model_type": model_type,
            "provider": "replicate",
            "gender": gender,
            "normalized_scene": normalized_scene,
            "outfit_decision": dict(outfit_decision or {}),
            "exposure_level": exposure_level,
            "positive_prompt": prompt,
            "negative_prompt": None,
            "positive_tokens": _estimate_prompt_tokens(prompt),
            "negative_tokens": 0,
            "replicate_input": dict(replicate_input),
            "replicate_model": replicate_model,
            "log_meta": dict(log_meta or {}),
        }
        prompt_metadata.update(
            _provider_prompt_metadata(
                provider="replicate",
                prompt=prompt,
                negative_prompt=negative_prompt,
                replicate_input=replicate_input,
            )
        )
        return PhotoPromptBundle(
            model_type=model_type,
            gender=gender,
            prompt=prompt,
            negative_prompt=negative_prompt,
            scene=normalized_scene,
            replicate_input=replicate_input,
            replicate_model=replicate_model,
            provider="replicate",
            state_meta_update=state_meta_update,
            prompt_metadata=prompt_metadata,
        )

    async def build_avatar_prompt_bundle(
        self,
        character: Mapping[str, Any],
        log_meta: Mapping[str, Any] | None = None,
    ) -> PhotoPromptBundle:
        policy = await get_photo_prompt_policy()
        avatar_character = _avatar_generation_character(character, policy)
        model_type = _normalize_model_type(avatar_character)
        prompt_model_type = "anime" if model_type == "manhwa" else model_type
        gender = _normalize_gender(avatar_character)
        _ensure_supported_model_gender(model_type, gender)
        visual = _visual_parts(avatar_character, policy)
        wardrobe = _wardrobe(avatar_character)
        clothing_prompt = _avatar_clothing_prompt(prompt_model_type, gender, visual, wardrobe, policy)
        template_model_type = "manhwa" if model_type == "manhwa" else prompt_model_type
        template = await get_prompt(f"photo_prompt_{template_model_type}_{gender}")
        if prompt_model_type == "anime":
            scene = dict(policy.avatar_scene)
            negative_template = await get_prompt(f"photo_negative_{template_model_type}_{gender}")
            anime_result = _build_anime_prompt_result(
                character=avatar_character,
                gender=gender,
                visual=visual,
                scene=scene,
                clothing_prompt=clothing_prompt,
                template=template,
                negative_template=negative_template,
                budget=ANIME_AVATAR_PROMPT_BUDGET,
                negative_budget=ANIME_NEGATIVE_BUDGET,
                purpose="avatar",
                log_meta=log_meta,
                policy=policy,
            )
            prompt = anime_result["prompt"]
            negative_prompt = anime_result["negative_prompt"]
            replicate_input = self._replicate_input(prompt_model_type, prompt, negative_prompt)
            provider = "runpod_manhwa" if model_type == "manhwa" else "replicate"
            replicate_model = "runpod:manhwa" if model_type == "manhwa" else ANIME_MODEL_VERSION
            prompt_metadata = dict(anime_result["metadata"])
            prompt_metadata["model_type"] = model_type
            prompt_metadata["provider"] = provider
            prompt_metadata["replicate_input"] = dict(replicate_input)
            prompt_metadata["replicate_model"] = replicate_model
            prompt_metadata.update(
                _provider_prompt_metadata(
                    provider=provider,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    replicate_input=replicate_input,
                )
            )
            return PhotoPromptBundle(
                model_type=model_type,
                gender=gender,
                prompt=prompt,
                negative_prompt=negative_prompt,
                scene=dict(anime_result["normalized_scene"]),
                replicate_input=replicate_input,
                replicate_model=replicate_model,
                provider=provider,
                prompt_metadata=prompt_metadata,
            )

        scene_description = (
            "An upper-body realistic portrait with the character looking at the camera "
            "against a simple softly lit background."
        )
        exposure_level = _anime_exposure_level(policy.avatar_scene, clothing_prompt)
        normalized_scene = {
            **dict(policy.avatar_scene),
            "scene_description": scene_description,
            "exposure_level": exposure_level,
        }
        outfit_decision = {"source": "avatar_default", "clothing": clothing_prompt}

        context = {
            "character_name": avatar_character.get("name", ""),
            "gender": gender,
            "subject_tags": visual["subject_tags"],
            "appearance": _strip_user_quality_tags(visual["appearance"], policy),
            "body": _strip_user_quality_tags(visual["body"], policy),
            "face": _strip_user_quality_tags(visual["face"], policy),
            "clothing": clothing_prompt,
            "scene_description": scene_description,
            "pose": policy.avatar_scene.get("pose", ""),
            "expression": policy.avatar_scene.get("expression", ""),
            "emotion": policy.avatar_scene.get("emotion", ""),
            "setting": policy.avatar_scene.get("setting", ""),
            "scene_notes": policy.avatar_scene.get("scene_notes", ""),
            "style_tags": visual["style_tags"],
        }

        removable_fields = ("scene_notes", "style_tags", "setting", "emotion")
        prompt = _fit_prompt_budget(
            template,
            context,
            PROMPT_BUDGETS[model_type],
            removable_fields=removable_fields,
            label=f"avatar/{model_type}/{gender}",
            log_meta=log_meta,
            renderer=_render_real_template,
        )

        negative_prompt = None

        replicate_input = self._replicate_input(prompt_model_type, prompt, negative_prompt)
        replicate_model = ANIME_MODEL_VERSION if prompt_model_type == "anime" else REAL_MODEL
        prompt_metadata = {
            "profile_version": "real_prompt_v1",
            "purpose": "avatar",
            "model_type": model_type,
            "provider": "replicate",
            "gender": gender,
            "normalized_scene": normalized_scene,
            "outfit_decision": outfit_decision,
            "exposure_level": exposure_level,
            "positive_prompt": prompt,
            "negative_prompt": None,
            "positive_tokens": _estimate_prompt_tokens(prompt),
            "negative_tokens": 0,
            "replicate_input": dict(replicate_input),
            "replicate_model": replicate_model,
            "log_meta": dict(log_meta or {}),
        }
        prompt_metadata.update(
            _provider_prompt_metadata(
                provider="replicate",
                prompt=prompt,
                negative_prompt=negative_prompt,
                replicate_input=replicate_input,
            )
        )
        return PhotoPromptBundle(
            model_type=model_type,
            gender=gender,
            prompt=prompt,
            negative_prompt=negative_prompt,
            scene=normalized_scene,
            replicate_input=replicate_input,
            replicate_model=replicate_model,
            provider="replicate",
            prompt_metadata=prompt_metadata,
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

    async def _run_bundle_provider(
        self,
        bundle: PhotoPromptBundle,
        *,
        on_runpod_job_created: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if bundle.provider == "runpod_manhwa":
            async def on_job(job_id: str, payload: dict[str, Any]) -> None:
                if on_runpod_job_created:
                    await on_runpod_job_created("runpod_manhwa", job_id, payload)

            try:
                image_url = await manhwa_provider.generate(
                    positive_prompt=bundle.prompt,
                    negative_prompt=bundle.negative_prompt or "",
                    on_job_created=on_job,
                )
            except manhwa_provider.ManhwaProviderError as e:
                raise PhotoProviderError(str(e)) from e
            return image_url, {"runpod_provider": "runpod_manhwa"}

        prediction = await self.replicate_client.run(bundle.replicate_model, bundle.replicate_input)
        image_url = self.replicate_client._first_output_url(prediction.get("output"))
        return image_url, {"provider_prediction_id": prediction.get("id")}

    async def generate_for_chat(
        self,
        session: AsyncSession,
        user: User,
        chat_id: int,
        character: Mapping[str, Any],
        recent_messages: Sequence[Message | Mapping[str, Any]],
        chat_state: Mapping[str, Any] | None = None,
        before_save: Callable[[], Awaitable[None]] | None = None,
        on_runpod_job_created: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None = None,
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

        image_url, provider_meta = await self._run_bundle_provider(
            bundle,
            on_runpod_job_created=on_runpod_job_created,
        )

        identity_source_image = _identity_source_image(character)
        face_swap_applied = False
        if identity_source_image:
            from shared.services.image_storage import ImageStorageError, local_image_to_data_url

            async def on_facefusion_job(job_id: str, payload: dict[str, Any]) -> None:
                if on_runpod_job_created:
                    await on_runpod_job_created("runpod_facefusion", job_id, payload)

            try:
                source_image_data = await local_image_to_data_url(identity_source_image)
                target_bytes, target_content_type, _target_provider_url = (
                    await self.replicate_client.download_output(image_url)
                )
                target_image_data = (
                    f"data:{target_content_type};base64,"
                    f"{base64.b64encode(target_bytes).decode('ascii')}"
                )
                image_url = await facefusion_provider.swap_face(
                    source_image=source_image_data,
                    target_image=target_image_data,
                    on_job_created=on_facefusion_job,
                )
                face_swap_applied = True
            except (facefusion_provider.FaceFusionError, ImageStorageError) as e:
                raise PhotoProviderError("Не удалось применить лицо к фото, попробуйте еще раз") from e

        image_bytes, content_type, provider_url = await self.replicate_client.download_output(image_url)
        if before_save:
            await before_save()
        local_path = await self._save_image_bytes(image_bytes, content_type, user.telegram_id)
        if before_save:
            try:
                await before_save()
            except Exception:
                self._delete_saved_image(local_path)
                raise

        prompt_metadata = dict(bundle.prompt_metadata or {})
        prompt_metadata.update({k: v for k, v in provider_meta.items() if v})
        if identity_source_image:
            prompt_metadata["identity_pipeline"] = True
            prompt_metadata["identity_source_image"] = identity_source_image
            prompt_metadata["face_swap_backend"] = "runpod_facefusion"
            prompt_metadata["face_swap_applied"] = face_swap_applied

        image = GeneratedImage(
            user_id=user.telegram_id,
            chat_id=chat_id,
            provider_url=None if face_swap_applied or not provider_url else provider_url,
            local_path=local_path,
            prompt=bundle.prompt,
            prompt_metadata=prompt_metadata,
            file_size=len(image_bytes),
            content_type=content_type,
        )
        await self._apply_state_meta_update(session, chat_id, bundle.state_meta_update)
        session.add(image)
        await session.commit()
        await session.refresh(image)
        logger.info(
            "Generated chat image: image_id=%s chat_id=%s model=%s provider=%s provider_meta=%s",
            image.id,
            chat_id,
            bundle.replicate_model,
            bundle.provider,
            provider_meta,
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

        image_url, provider_meta = await self._run_bundle_provider(bundle)
        image_bytes, content_type, _provider_url = await self.replicate_client.download_output(image_url)
        public_url = await save_avatar_image(image_bytes, content_type, character_id)
        logger.info(
            "Generated character avatar: character_id=%s model=%s provider=%s provider_meta=%s",
            character_id,
            bundle.replicate_model,
            bundle.provider,
            provider_meta,
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
