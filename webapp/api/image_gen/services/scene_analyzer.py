import json
import logging
import re
from typing import Optional
from pydantic import BaseModel
from shared.services.llm import LLMClient

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """Извлекает JSON из ответа LLM, даже если он обёрнут в markdown."""
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

    return result


class SceneAnalysis(BaseModel):
    location: str = "unknown"
    pose: str = "standing"
    outfit_key: str = "default_outfit"
    emotion: str = "neutral"
    nsfw_level: int = 0
    reasoning: str = ""


def calculate_nsfw_fallback(arousal: int, affinity: int) -> int:
    score = arousal * 0.75 + affinity * 0.25
    return min(5, max(0, int(score / 20)))


class SceneAnalyzer:

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def analyze(
        self,
        history: list[dict],
        character_name: str,
        available_outfits: list[str]
    ) -> SceneAnalysis:
        recent_messages = history[-5:] if len(history) > 5 else history
        formatted = "\n".join([
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in recent_messages
        ])

        prompt = f"""Scene: {character_name}
Chat:
{formatted}

Outfits: {', '.join(available_outfits)}

Return ONLY this JSON (no markdown, no nesting):
{{"location":"string","pose":"string","outfit_key":"one from outfits list","emotion":"string","nsfw_level":0-5,"reasoning":"string"}}

nsfw: 0=public/clothed, 2=suggestive, 4=explicit"""

        try:
            response = await self.llm.generate(
                system_prompt="Return ONLY flat JSON. No markdown. No nested objects. No explanations.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.1
            )

            logger.info(f"SceneAnalyzer LLM raw response: {response[:500]}")

            data = extract_json(response)
            data = normalize_scene_data(data)
            return SceneAnalysis(**data)

        except Exception as e:
            logger.error(f"SceneAnalyzer parse error: {str(e)}")
            return SceneAnalysis(
                reasoning=f"Fallback due to error: {str(e)}"
            )
