"""OpenRouter vision identity reference analysis for custom-photo characters."""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from shared.config import OPENROUTER_IDENTITY_MODEL, OPENROUTER_IDENTITY_TIMEOUT_SECONDS
from shared.services.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = (
    "You describe consenting adult identity reference images for downstream image "
    "generation and face swap. Return ONLY valid JSON. Do not identify the person, "
    "name them, infer private facts, infer body shape, or include scene, pose, "
    "clothing, sexual content, or hidden traits."
)

VISION_USER_PROMPT = """
Analyze the attached consenting adult identity reference image.

Return one flat JSON object with this exact shape:
{
  "identity_prompt": "compact English prompt describing only visible appearance traits useful for generation before a face swap",
  "visible_traits": {
    "hair": "...",
    "skin": "...",
    "eyes": "...",
    "makeup": "...",
    "accessories": "...",
    "adult_age_range": "...",
    "face_vibe": "..."
  },
  "avoid": ["short drift risk", "short drift risk"],
  "notes": "short caveat or empty string"
}

Rules:
- The final face will be swapped by another model, so prioritize visible traits that
  should survive target generation: hair color, hair texture, hair length, skin tone,
  eye color, makeup style, accessories, and overall adult face vibe.
- Do not infer body type, breast/waist/hip shape, height, weight, personality,
  ethnicity, nationality, name, or exact age.
- If a detail is uncertain, say "uncertain" rather than inventing it.
- Keep identity_prompt under 90 words.
""".strip()

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class IdentityReferenceError(RuntimeError):
    pass


def parse_identity_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    match = _FENCED_JSON_RE.search(text)
    if match:
        text = match.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise IdentityReferenceError("OpenRouter identity response was not valid JSON") from e
    if not isinstance(parsed, dict):
        raise IdentityReferenceError("OpenRouter identity response must be a JSON object")
    return parsed


def normalize_identity_reference(parsed: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    visible_traits = parsed.get("visible_traits")
    if not isinstance(visible_traits, dict):
        visible_traits = {}
    visible_traits = {
        str(key): str(value).strip()
        for key, value in visible_traits.items()
        if value not in (None, "")
    }

    avoid = parsed.get("avoid")
    if not isinstance(avoid, list):
        avoid = []
    avoid = [str(item).strip() for item in avoid if str(item).strip()]

    identity_prompt = str(parsed.get("identity_prompt") or "").strip()
    if not identity_prompt:
        fallback_parts = [value for value in visible_traits.values() if value and value != "uncertain"]
        identity_prompt = ", ".join(fallback_parts[:6]) or "adult face reference with visible natural facial traits"

    return {
        "identity_prompt": identity_prompt,
        "visible_traits": visible_traits,
        "avoid": avoid,
        "notes": str(parsed.get("notes") or "").strip(),
        "model": model or OPENROUTER_IDENTITY_MODEL,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


async def analyze(image_data_url: str) -> dict[str, Any]:
    """Analyze an adult consented identity reference image without storing raw data."""
    if not image_data_url.startswith("data:image/"):
        raise IdentityReferenceError("Identity analysis requires a data:image URL")

    llm = LLMClient(
        model=OPENROUTER_IDENTITY_MODEL,
        provider={"sort": "latency"},
        reasoning={"enabled": False},
        timeout=OPENROUTER_IDENTITY_TIMEOUT_SECONDS,
        max_retries=1,
    )
    try:
        response = await llm.generate(
            system_prompt=VISION_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            max_tokens=500,
            temperature=0.1,
            extra_payload={"response_format": {"type": "json_object"}},
        )
    except LLMError as e:
        logger.warning("Identity reference analysis failed via OpenRouter: %s", e)
        raise IdentityReferenceError("Identity reference analysis failed") from e

    parsed = parse_identity_json(response.content)
    return normalize_identity_reference(parsed, model=response.model or OPENROUTER_IDENTITY_MODEL)
