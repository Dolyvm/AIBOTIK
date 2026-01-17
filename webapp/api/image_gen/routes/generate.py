import json
import logging
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException, Body, Query

from shared.models import Chat
from shared.repository import get_session, get_user
from shared.services.content_loader import get_character, get_world
from shared.services.llm import LLMClient
from shared.config import SCENE_ANALYZER_ENABLED, SCENE_ANALYZER_MODEL
from ..schemas.generate import GenerateRequest, ModelType, Prompt
from ..services.generate import submit_anime, submit_real
from ..services.scene_analyzer import SceneAnalyzer, calculate_nsfw_fallback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(sys.stdout)
    ]
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
async def gen(
    chat_id: int,
    outfit: str = Query(default="default_outfit", description="Ключ из wardrobe (casual, formal, gym, swimwear, sleepwear, underwear, nude)"),
    use_smart_analysis: bool = Query(default=True, description="Использовать LLM анализ сцены")
):
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
    history = json.loads(chat.history)

    nsfw_level = 0
    outfit_key = outfit
    environment = ""
    scene_reasoning = ""

    if use_smart_analysis and SCENE_ANALYZER_ENABLED and history:
        try:
            llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)
            analyzer = SceneAnalyzer(llm_client)

            visual = content.get("visual", {})
            wardrobe = visual.get("wardrobe", {})
            available_outfits = ["default_outfit"] + list(wardrobe.keys())

            scene = await analyzer.analyze(
                history=history,
                character_name=content["name"],
                available_outfits=available_outfits
            )

            nsfw_level = scene.nsfw_level
            outfit_key = scene.outfit_key
            environment = scene.location
            scene_reasoning = scene.reasoning

            logging.info(f"Scene analysis: {scene_reasoning}")

        except Exception as e:
            logging.warning(f"Scene analysis failed, using fallback: {e}")
            nsfw_level = calculate_nsfw_fallback(state["arousal"], state["affinity"])
            outfit_key = outfit
            environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")
    else:
        nsfw_level = calculate_nsfw_fallback(state["arousal"], state["affinity"])
        environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")

    prompt = Prompt.from_character(
        character=content,
        outfit_key=outfit_key,
        nsfw_level=nsfw_level,
        environment=environment
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
