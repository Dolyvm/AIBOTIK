import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from shared.models import Prompt
from shared.database import get_session
from shared.services.prompt_service import DEFAULT_PROMPTS


PROMPT_METADATA = {
    "llm_active_model": {
        "category": "settings",
        "name": "Active LLM Model"
    },
    "common_style_guide": {
        "category": "character",
        "name": "Common Style Guide"
    },
    "meta_instruction": {
        "category": "character",
        "name": "Meta Instruction (JSON)"
    },
    "character_prompt_template": {
        "category": "character",
        "name": "Character Prompt Template"
    },
    "world_prompt_template": {
        "category": "character",
        "name": "World Prompt Template"
    },

    "behavior_affinity_cold": {
        "category": "character",
        "name": "Behavior: Cold (Affinity 0-19)"
    },
    "behavior_affinity_neutral": {
        "category": "character",
        "name": "Behavior: Neutral (Affinity 20-49)"
    },
    "behavior_affinity_warm": {
        "category": "character",
        "name": "Behavior: Warm (Affinity 50-79)"
    },
    "behavior_affinity_love": {
        "category": "character",
        "name": "Behavior: Love (Affinity 80+)"
    },
    "behavior_arousal_high": {
        "category": "character",
        "name": "Behavior: High Arousal (>50)"
    },

    "player_prompt": {
        "category": "player",
        "name": "Player Auto-Message Generation"
    },

    "summary_prompt": {
        "category": "summary",
        "name": "History Summarization"
    },

    "scene_analyzer_prompt": {
        "category": "scene_analysis",
        "name": "Scene Analysis for Image Generation"
    },

    "nsfw_level_0": {
        "category": "image",
        "name": "NSFW Level 0 (SFW) - Positive"
    },
    "nsfw_level_0_neg": {
        "category": "image",
        "name": "NSFW Level 0 (SFW) - Negative"
    },
    "nsfw_level_1": {
        "category": "image",
        "name": "NSFW Level 1 (Teasing) - Positive"
    },
    "nsfw_level_1_neg": {
        "category": "image",
        "name": "NSFW Level 1 (Teasing) - Negative"
    },
    "nsfw_level_2": {
        "category": "image",
        "name": "NSFW Level 2 (Revealing) - Positive"
    },
    "nsfw_level_2_neg": {
        "category": "image",
        "name": "NSFW Level 2 (Revealing) - Negative"
    },
    "nsfw_level_3": {
        "category": "image",
        "name": "NSFW Level 3 (Topless) - Positive"
    },
    "nsfw_level_3_neg": {
        "category": "image",
        "name": "NSFW Level 3 (Topless) - Negative"
    },
    "nsfw_level_4": {
        "category": "image",
        "name": "NSFW Level 4 (Nude) - Positive"
    },
    "nsfw_level_4_neg": {
        "category": "image",
        "name": "NSFW Level 4 (Nude) - Negative"
    },
    "nsfw_level_5": {
        "category": "image",
        "name": "NSFW Level 5 (Explicit) - Positive"
    },
    "nsfw_level_5_neg": {
        "category": "image",
        "name": "NSFW Level 5 (Explicit) - Negative"
    },

    "anime_base_positive": {
        "category": "image",
        "name": "Anime Base Positive Prompt"
    },
    "anime_base_negative": {
        "category": "image",
        "name": "Anime Base Negative Prompt"
    },
    "manhwa_base_positive": {
        "category": "image",
        "name": "Manhwa Base Positive Prompt"
    },
    "manhwa_base_negative": {
        "category": "image",
        "name": "Manhwa Base Negative Prompt"
    },

    "character_modifiers_emily_stage_1": {
        "category": "modifiers",
        "name": "Emily - Stage 1 (Affinity 0-20)"
    },
    "character_modifiers_emily_stage_2": {
        "category": "modifiers",
        "name": "Emily - Stage 2 (Affinity 20-50)"
    },
    "character_modifiers_emily_stage_3": {
        "category": "modifiers",
        "name": "Emily - Stage 3 (Affinity 50-80)"
    },
    "character_modifiers_emily_stage_4": {
        "category": "modifiers",
        "name": "Emily - Stage 4 (Affinity 80+)"
    },
    "character_modifiers_aiko_stage_1": {
        "category": "modifiers",
        "name": "Aiko - Stage 1 (Affinity 0-20)"
    },
    "character_modifiers_aiko_stage_2": {
        "category": "modifiers",
        "name": "Aiko - Stage 2 (Affinity 20-50)"
    },
    "character_modifiers_aiko_stage_3": {
        "category": "modifiers",
        "name": "Aiko - Stage 3 (Affinity 50-80)"
    },
    "character_modifiers_aiko_stage_4": {
        "category": "modifiers",
        "name": "Aiko - Stage 4 (Affinity 80+)"
    },

    "meta_instruction_sfw": {
        "category": "character",
        "name": "Meta Instruction (SFW Mode)"
    },
    "behavior_arousal_high_sfw": {
        "category": "character",
        "name": "Behavior: High Arousal (SFW)"
    },
    "sfw_content_restriction": {
        "category": "character",
        "name": "SFW Content Restriction"
    },
    "scene_analyzer_prompt_sfw": {
        "category": "scene_analysis",
        "name": "Scene Analyzer (SFW)"
    },
}


async def init_prompts():
    async with get_session() as db:
        result = await db.execute(select(Prompt))
        existing_prompts = {p.key: p for p in result.scalars().all()}

        created_count = 0
        updated_count = 0

        for key, content in DEFAULT_PROMPTS.items():
            metadata = PROMPT_METADATA.get(key)
            if not metadata:
                continue

            if key in existing_prompts:
                pass  # don't overwrite manually edited prompts
            else:
                prompt = Prompt(
                    key=key,
                    category=metadata["category"],
                    name=metadata["name"],
                    content=content
                )
                db.add(prompt)
                created_count += 1

        await db.commit()


if __name__ == "__main__":
    asyncio.run(init_prompts())
