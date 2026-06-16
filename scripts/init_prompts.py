import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from shared.models import Prompt
from shared.database import get_session
from shared.services.cache import CacheService, get_cache, set_cache
from shared.services.redis_client import get_redis
from shared.services.prompt_service import (
    COMPACT_RUNTIME_PROMPT_KEYS,
    DEFAULT_PROMPTS,
    PHOTO_PROMPT_KEYS,
    clear_cache,
)


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

    "photo_scene_extractor": {
        "category": "photo",
        "name": "Photo Scene Extractor"
    },
    "photo_prompt_real_female": {
        "category": "photo",
        "name": "Photo Prompt: Real Female"
    },
    "photo_prompt_real_male": {
        "category": "photo",
        "name": "Photo Prompt: Real Male"
    },
    "photo_prompt_anime_female": {
        "category": "photo",
        "name": "Photo Prompt: Anime Female"
    },
    "photo_prompt_anime_male": {
        "category": "photo",
        "name": "Photo Prompt: Anime Male"
    },
    "photo_negative_anime_female": {
        "category": "photo",
        "name": "Photo Negative Prompt: Anime Female"
    },
    "photo_negative_anime_male": {
        "category": "photo",
        "name": "Photo Negative Prompt: Anime Male"
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
}


async def ensure_cache_service():
    if get_cache():
        return
    try:
        set_cache(CacheService(await get_redis()))
    except Exception as e:
        print(f"Redis cache unavailable; prompts will only be synced to DB: {e}")


async def refresh_prompt_cache(keys: set[str] | frozenset[str]):
    await ensure_cache_service()
    await clear_cache()

    cache = get_cache()
    if not cache:
        return

    for key in keys:
        content = DEFAULT_PROMPTS.get(key)
        if content is not None:
            await cache.set_prompt(key, content)


async def init_prompts(sync_compact: bool = False, sync_photo: bool = False):
    sync_keys = set()
    if sync_compact:
        sync_keys.update(COMPACT_RUNTIME_PROMPT_KEYS)
    if sync_photo:
        sync_keys.update(PHOTO_PROMPT_KEYS)

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
                if key in sync_keys:
                    prompt = existing_prompts[key]
                    if prompt.content != content:
                        prompt.content = content
                        updated_count += 1
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

    if sync_keys:
        await refresh_prompt_cache(sync_keys)

    modes = []
    if sync_compact:
        modes.append("sync-compact")
    if sync_photo:
        modes.append("sync-photo")
    mode = "+".join(modes) if modes else "create-missing"
    print(f"Prompts initialized ({mode}): created={created_count}, updated={updated_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sync-compact",
        action="store_true",
        help="Update only compact runtime prompt keys in DB and invalidate prompt cache.",
    )
    parser.add_argument(
        "--sync-photo",
        action="store_true",
        help="Update only photo prompt keys in DB and invalidate prompt cache.",
    )
    args = parser.parse_args()

    asyncio.run(
        init_prompts(
            sync_compact=args.sync_compact,
            sync_photo=args.sync_photo,
        )
    )
