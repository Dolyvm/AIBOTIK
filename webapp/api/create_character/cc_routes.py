import sys
from pathlib import Path
from fastapi import APIRouter
from fastapi import APIRouter, HTTPException, Body, Depends

from shared.config import SCENE_ANALYZER_MODEL
from shared.services.llm import LLMClient
from .cc_schemas import CreateCharacterRequest
from .cc_service import personality_to_prompt, stepsList, build_llm_prompt

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import Chat, User, Character
from shared.repository import get_session
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership

router = APIRouter(prefix="/api/create_character", tags=["create_character"])


@router.post("")
async def create_character_endpoint(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
    async with get_session() as session:
        character = Character(
            id=payload.name,
            name=payload.name,
            description="",  # пока похуй
            personality=personality_to_prompt[payload.personality],
            visual_data=payload.build_visual(),
        )
        session.add(character)
        await session.commit()
    return 201


@router.get("")
async def get_create_character_data(user: User = Depends(get_current_user)):
    return stepsList


@router.post("/scenario")
async def create_character_endpoint(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
    prompt = build_llm_prompt(payload)
    llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)
    response = await llm_client.generate(
        system_prompt=system_prompt,
    )
