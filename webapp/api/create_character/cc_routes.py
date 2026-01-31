import logging
import uuid
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, Depends

from shared.config import SCENE_ANALYZER_MODEL
from shared.services.llm import LLMClient
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from .cc_schemas import CreateCharacterRequest
from .cc_service import (
    stepsList,
    build_llm_prompt,
    build_description_prompt,
    build_first_mes_prompt,
    generate_tags,
    build_personality_with_preferences
)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import User, Character
from shared.database import get_session
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership

router = APIRouter(prefix="/api/create_character", tags=["create_character"])

@router.post("")
async def create_character_endpoint(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
                         
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        limits = RATE_LIMITS["character_creation"]
        allowed = await rate_limiter.is_allowed(
            key=f"character_creation:user:{user.telegram_id}",
            limit=limits["limit"],
            window=limits["window"]
        )
        if not allowed:
            raise RateLimitExceeded(
                limit=limits["limit"],
                window=limits["window"],
                retry_after=limits["retry_after"]
            )

    try:
        character_id = f"custom_{user.telegram_id}_{uuid.uuid4().hex[:8]}"

        scenarios = []
        if payload.first_mes or payload.scenario:
            scenarios.append({
                "index": 0,
                "intro": payload.first_mes or "",
                "scenario": payload.scenario or ""
            })

        tags = generate_tags(payload)

        personality = build_personality_with_preferences(payload)

        description = payload.description or (
            f"{payload.name} — {payload.age}-летняя {payload.nationality} "
            f"по профессии {payload.job}. Характер: {payload.personality}."
        )

        async with get_session() as session:
            character = Character(
                id=character_id,
                name=payload.name,
                description=description,
                personality=personality,
                visual_data=payload.build_visual(),
                scenarios=scenarios,
                tags=tags,
                is_nsfw=True,
                created_by_username_id = user.telegram_id,
                created_by_username = user.username,
            )
            session.add(character)
            await session.commit()
        return {"character_id": character_id, "status": "created"}
    except Exception as e: 
        logging.error(f"[CREATE_CHARACTER] Error: {e}")
        raise HTTPException(status_code=500, detail={
            "error": "creation_failed",
            "message": "Не удалось создать персонажа",
            "code": "CHARACTER_CREATION_FAILED"
        })

@router.get("")
async def get_create_character_data(user: User = Depends(get_current_user)):
    return stepsList

@router.post("/scenario")
async def generate_character_scenario(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
                                    
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_llm_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["llm"]
            raise RateLimitExceeded(
                limit=limits["limit"],
                window=limits["window"],
                retry_after=limits["retry_after"]
            )

    try:
        llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)

        scenario_prompt = await build_llm_prompt(payload)
        scenario = await llm_client.generate(
            system_prompt=scenario_prompt,
            messages=[],
            max_tokens=500,
            temperature=0.75
        )

        first_mes_prompt = await build_first_mes_prompt(payload, scenario)
        first_mes = await llm_client.generate(
            system_prompt=first_mes_prompt,
            messages=[],
            max_tokens=800,
            temperature=0.75
        )

        description_prompt = await build_description_prompt(payload)
        description = await llm_client.generate(
            system_prompt=description_prompt,
            messages=[],
            max_tokens=500,
            temperature=0.7
        )

        return {
            "scenario": scenario,
            "first_mes": first_mes,
            "description": description
        }
    except Exception as e:
        logging.error(f"[CREATE_CHARACTER] LLM error: {e}")
        raise HTTPException(status_code=500, detail={
            "error": "generation_failed",
            "message": "Ошибка генерации сценария",
            "code": "SCENARIO_GENERATION_FAILED"
        })
