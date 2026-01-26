import uuid
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, Depends

from shared.config import SCENE_ANALYZER_MODEL
from shared.services.llm import LLMClient
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
from shared.repository import get_session
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership

router = APIRouter(prefix="/api/create_character", tags=["create_character"])


@router.post("")
async def create_character_endpoint(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
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
        )
        session.add(character)
        await session.commit()

    return {"character_id": character_id, "status": "created"}


@router.get("")
async def get_create_character_data(user: User = Depends(get_current_user)):
    return stepsList


@router.post("/scenario")
async def generate_character_scenario(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
    llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)

    scenario_prompt = build_llm_prompt(payload)
    scenario = await llm_client.generate(
        system_prompt=scenario_prompt,
        messages=[],
        max_tokens=500,
        temperature=0.75
    )

    first_mes_prompt = build_first_mes_prompt(payload, scenario)
    first_mes = await llm_client.generate(
        system_prompt=first_mes_prompt,
        messages=[],
        max_tokens=800,
        temperature=0.75
    )

    description_prompt = build_description_prompt(payload)
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
