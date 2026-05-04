import hashlib
import json
import logging
import re
from typing import Optional, Union
from pydantic import BaseModel
from shared.services.llm import LLMClient
from shared.services.cache import get_cache

logger = logging.getLogger(__name__)

def extract_json(text: str) -> dict:
    text = text.strip()

    if text.startswith('{'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find('{')
    if start != -1:
        depth = 0
        for i, char in enumerate(text[start:], start):
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract JSON from response")

def normalize_scene_data(data: dict) -> dict:
    if 'scene_analysis' in data:
        data = data['scene_analysis']

    result = {}

    loc = data.get('location', 'unknown')
    if isinstance(loc, dict):
        result['location'] = loc.get('subtype') or loc.get('type') or loc.get('name') or 'unknown'
    else:
        result['location'] = str(loc) if loc else 'unknown'

    pose = data.get('pose', 'standing')
    if isinstance(pose, dict):
        result['pose'] = pose.get('description') or pose.get('type') or 'standing'
    else:
        result['pose'] = str(pose) if pose else 'standing'

    outfit = data.get('outfit_key') or data.get('outfit') or (data.get('clothing', {}).get('key') if isinstance(data.get('clothing'), dict) else None)
    if isinstance(outfit, dict):
        outfit = outfit.get('key') or outfit.get('type') or 'default_outfit'
    result['outfit_key'] = str(outfit) if outfit else 'default_outfit'

    emotion = data.get('emotion', 'neutral')
    if isinstance(emotion, dict):
        result['emotion'] = emotion.get('primary') or emotion.get('type') or 'neutral'
    else:
        result['emotion'] = str(emotion) if emotion else 'neutral'

    nsfw = data.get('nsfw_level', 0)
    if isinstance(nsfw, dict):
        nsfw = nsfw.get('level') or nsfw.get('value') or 0
    try:
        result['nsfw_level'] = max(0, min(5, int(nsfw)))
    except (ValueError, TypeError):
        result['nsfw_level'] = 0

    result['reasoning'] = str(data.get('reasoning', '')) if data.get('reasoning') else ''
    result['scene_description'] = str(data.get('scene_description', '')) if data.get('scene_description') else ''
    result['nsfw_tags'] = str(data.get('nsfw_tags', '')) if data.get('nsfw_tags') else ''

    return result

class SceneAnalysis(BaseModel):
    location: str = "unknown"
    pose: str = "standing"
    outfit_key: str = "default_outfit"
    emotion: str = "neutral"
    nsfw_level: int = 0
    reasoning: str = ""
    scene_description: str = ""
    nsfw_tags: str = ""  # compact NSFW visual tags (max 5-6), filled only at levels 4-5

NSFW_KEYWORD_MAP = {
    # Bodily fluids
    "cum on face": "cum on face",
    "cum on body": "cum on body",
    "cum on breast": "cum on breasts",
    "cum on chest": "cum on breasts",
    "cum drip": "cum dripping",
    "cum streak": "cum on body",
    "semen": "cum on body",
    "facial": "cum on face",
    "creampie": "creampie",
    "squirt": "squirting",
    "saliva": "saliva",
    "drool": "saliva",
    # Positions
    "all fours": "on all fours",
    "doggy": "doggy style",
    "missionary": "missionary",
    "cowgirl": "cowgirl",
    "riding": "riding",
    "bent over": "bent over",
    "spread legs": "spread legs",
    "legs spread": "spread legs",
    "kneeling": "kneeling",
    # Acts
    "blowjob": "blowjob",
    "oral": "oral sex",
    "deepthroat": "deepthroat",
    "penetrat": "penetration",
    "intercourse": "sex",
    "masturbat": "masturbation",
    "finger": "fingering",
    # Expressions
    "ahegao": "ahegao",
    "tongue out": "tongue out",
    "eyes rolled": "rolling eyes",
    "open mouth": "open mouth",
    "moaning": "moaning expression",
    # Physical state
    "sweat": "sweaty skin",
    "flush": "flushed skin",
    "tremble": "trembling body",
    "erect nipple": "erect nipples",
    "hard nipple": "erect nipples",
}


def extract_nsfw_tags_fallback(scene_description: str, pose: str = "") -> str:
    """Extract NSFW tags from scene_description when LLM doesn't provide nsfw_tags."""
    if not scene_description:
        return ""

    text = (scene_description + " " + pose).lower()
    found_tags = []
    seen = set()

    for keyword, tag in NSFW_KEYWORD_MAP.items():
        if keyword in text and tag not in seen:
            found_tags.append(tag)
            seen.add(tag)
            if len(found_tags) >= 6:
                break

    return ", ".join(found_tags)


def calculate_nsfw_fallback(arousal: int, affinity: int) -> int:
    score = arousal * 0.75 + affinity * 0.25
    return min(5, max(0, int(score / 20)))

def calculate_sfw_fallback(arousal: int, affinity: int) -> int:
    return 1 if affinity > 50 else 0

class SceneAnalyzer:

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    NEGATIVE_MOODS = {"angry", "furious", "disgusted", "sad", "crying", "scared", "offended", "irritated"}
    REAL_SCENE_RULES_COMMON = """

REAL MODEL EXTRA RULES:
- The final image is a single-subject image of the named adult character only.
- Keep pose, nsfw_tags, and scene_description focused on that character's body, expression, and lighting.
- Do not invent age, nationality, face shape, breast shape, or nipple shape here; those are handled by the character prompt.
"""
    REAL_SCENE_RULES_FEMALE = """
- For female characters, NEVER put male anatomy terms in pose/nsfw_tags: no penis, cock, dick, testicles, futanari, bulge, strap-on.
- For female characters at nsfw_level 4-5, describe only anatomically female nude details and her own pose/expression.
- For real female characters, prefer idealized attractive adult proportions: fit body, smooth firm skin, no cellulite, no sagging, no belly folds.
"""

    @staticmethod
    def _format_outfits(outfits) -> str:
        if isinstance(outfits, dict):
            return "\n".join(
                f"- {k}: {v}" if v else f"- {k}"
                for k, v in outfits.items()
            )
        return ", ".join(outfits)

    @classmethod
    def _apply_model_specific_rules(cls, prompt: str, model_type: str, gender: str) -> str:
        if model_type != "real":
            return prompt

        rules = cls.REAL_SCENE_RULES_COMMON
        if gender == "male":
            return prompt + rules
        return prompt + rules + cls.REAL_SCENE_RULES_FEMALE

    async def analyze(
        self,
        history: list[dict],
        character_name: str,
        available_outfits: Union[list[str], dict[str, str]],
        allow_nsfw: bool = True,
        chat_id: int = None,
        mood: str = "neutral",
        affinity: int = 50,
        arousal: int = 0,
        current_location: str = "",
        model_type: str = "anime",
        gender: str = "female",
    ) -> SceneAnalysis:
        from shared.services.prompt_service import get_prompt

        recent_messages = history[-2:] if len(history) > 2 else history

        scene_prompt_profile = (
            f"real-rules-v2:{gender}" if model_type == "real" else f"base-v1:{model_type}:{gender}"
        )
        context_str = f"{character_name}:{allow_nsfw}:{scene_prompt_profile}:{recent_messages}"
        context_hash = hashlib.md5(context_str.encode()).hexdigest()[:16]

        cache = get_cache()
        if cache and chat_id:
            cached = await cache.get_scene_analysis(chat_id, context_hash)
            if cached:
                logger.info(f"SceneAnalysis cache HIT for chat {chat_id}")
                return SceneAnalysis(**cached)

        formatted = "\n".join([
            f"{m['role'].upper()}: {m['content']}"
            for m in recent_messages
        ])

        prompt_key = "scene_analyzer_prompt" if allow_nsfw else "scene_analyzer_prompt_sfw"
        try:
            prompt_template = await get_prompt(prompt_key)
        except KeyError:
            logger.warning(f"Prompt '{prompt_key}' not found, falling back to default")
            prompt_template = await get_prompt("scene_analyzer_prompt")

        is_male = gender == "male"
        gender_possessive = "HIS" if is_male else "HER"
        if is_male:
            pose_examples = '"standing dominant position", "lying on back relaxed", "sitting with legs apart", "thrusting from behind", "leaning against wall"'
            nsfw_level_3_desc = "shirtless, partial nudity, exposed chest"
        else:
            pose_examples = '"on all fours ass up", "legs spread lying on back", "bent over table", "kneeling between legs", "riding cowgirl position", "lying on side leg raised"'
            nsfw_level_3_desc = "exposed breasts"

        prompt = prompt_template.format(
            character_name=character_name,
            formatted_chat=formatted,
            available_outfits=self._format_outfits(available_outfits),
            mood=mood,
            affinity=affinity,
            arousal=arousal,
            current_location=current_location or "unknown",
            model_type=model_type,
            gender_possessive=gender_possessive,
            pose_examples=pose_examples,
            nsfw_level_3_desc=nsfw_level_3_desc,
        )
        prompt = self._apply_model_specific_rules(prompt, model_type, gender)

        try:
            llm_response = await self.llm.generate(
                system_prompt="Return ONLY flat JSON. No markdown. No nested objects. No explanations.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=350,
                temperature=0.1,
                extra_payload={"response_format": {"type": "json_object"}},
            )
            response = llm_response.content

            logger.info(f"SceneAnalyzer LLM raw response: {response[:500]}")

            data = extract_json(response)
            data = normalize_scene_data(data)
            scene = SceneAnalysis(**data)

            if not allow_nsfw:
                scene.nsfw_level = min(scene.nsfw_level, 1)

            if mood.lower() in self.NEGATIVE_MOODS:
                scene.nsfw_level = min(scene.nsfw_level, 1)
                logger.info(f"nsfw_level capped to {scene.nsfw_level} due to negative mood '{mood}'")

            original_outfit = scene.outfit_key
            outfit_keys = set(available_outfits.keys()) if isinstance(available_outfits, dict) else set(available_outfits)

            if scene.nsfw_level >= 4 and scene.outfit_key != "nude" and "nude" in outfit_keys:
                scene.outfit_key = "nude"
            elif scene.nsfw_level == 3 and scene.outfit_key not in ("nude", "underwear"):
                if "underwear" in outfit_keys:
                    scene.outfit_key = "underwear"
            elif scene.nsfw_level == 2 and scene.outfit_key not in ("underwear", "swimwear", "sleepwear", "nude"):
                if "swimwear" in outfit_keys:
                    scene.outfit_key = "swimwear"
            elif scene.nsfw_level <= 1 and scene.outfit_key in ("nude", "underwear"):
                scene.outfit_key = "default_outfit"

            if original_outfit != scene.outfit_key:
                logger.info(f"Outfit overridden: {original_outfit} -> {scene.outfit_key} (nsfw_level={scene.nsfw_level})")

            # Fallback: extract nsfw_tags from scene_description if LLM didn't provide them
            if scene.nsfw_level >= 4 and not scene.nsfw_tags:
                scene.nsfw_tags = extract_nsfw_tags_fallback(scene.scene_description, scene.pose)
                if scene.nsfw_tags:
                    logger.info(f"nsfw_tags extracted from scene_description: {scene.nsfw_tags}")

            if cache and chat_id:
                await cache.set_scene_analysis(chat_id, context_hash, scene.model_dump())

            return scene

        except Exception as e:
            logger.error(f"SceneAnalyzer parse error: {str(e)}")
            return SceneAnalysis(
                reasoning=f"Fallback due to error: {str(e)}"
            )
