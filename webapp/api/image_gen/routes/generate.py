import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Body

from shared.models import Chat
from shared.repository import get_session, get_user
from shared.services.content_loader import get_character, get_world
from ..schemas.generate import GenerateRequest, ModelType, Prompt
from ..services.generate import submit_anime, submit_real

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="app.log"
)

router = APIRouter(prefix="/api/image-gen", tags=["image-gen"])


@router.post("/build_prompt")
async def build_prompt_endpoint(data: Prompt, model_type: Optional[ModelType] = None):
    return data.build_prompt(model_type)


@router.post("/generate")
async def generate_image(data: GenerateRequest):
    result = None
    if data.model_type == ModelType.anime:
        result = await submit_anime(
            data.prompt, data.negative_prompt
        )
    elif data.model_type == ModelType.real:
        result = await submit_real(
            prompt=data.prompt,
            allow_nsfw=data.allow_nsfw
        )
    return result


@router.post("/{chat_id}/generate")
async def gen(chat_id: int):
    async with await get_session() as session:
        try:
            chat = await session.get(Chat, chat_id)

            if not chat:
                raise HTTPException(status_code=404, detail="Chat not found")

            if chat.chat_type == "character":
                content = get_character(chat.target_id)
                character, world = content, None
            else:
                content = get_world(chat.target_id)
                character, world = None, content

            if not content:
                raise HTTPException(status_code=404, detail="Content not found")

        except Exception as e:
            print(f"Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    state = json.loads(chat.state)

    score = state["arousal"] * 0.75 + state["affinity"] * 0.25
    nsfw_level = min(5, max(0, int(score / 20)))  # 0 .. 5 -> NSFWLevel
    prompt = Prompt(
        character_base=content.get("appearance"),
        environment=", ".join(content.get("tags", [])).replace("NSFW, ", ""),
        nsfw_level=nsfw_level
    )
    pos, neg = prompt.build_prompt(content.get("model_type"))
    result = None
    logging.info(f"{content=}")
    if content.get("model_type") == "anime":
        result = await submit_anime(pos, neg)

    elif content.get("model_type") == "real":
        result = await submit_real(
            prompt=pos,
            allow_nsfw=True
        )
    return result
