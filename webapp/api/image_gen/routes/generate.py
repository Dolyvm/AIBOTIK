import json
import logging
import sys
from pathlib import Path
from typing import Optional

from ...create_character.cc_schemas import CreateCharacterRequest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, HTTPException, Body, Query, Depends

from shared.models import Chat, User
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership
from shared.repository import get_session, get_user, save_generated_image, get_chat_history, update_chat_metrics
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
    nsfw_keywords = ["nsfw", "nude", "naked", "explicit", "erotic", "orgasm", "masturbat", "penetrat", "sex"]
    prompt_lower = data.prompt.lower()
    inferred_nsfw = sum(1 for kw in nsfw_keywords if kw in prompt_lower)
    nsfw_level = min(5, inferred_nsfw)

    image_url = None
    if data.model_type == ModelType.anime:
        image_url = await submit_anime(
            data.prompt, data.negative_prompt
        )
    elif data.model_type == ModelType.real:
        image_url = await submit_real(
            prompt=data.prompt,
            allow_nsfw=data.allow_nsfw,
            nsfw_level=nsfw_level
        )
    return {"url": image_url} if image_url else {"error": "Failed to generate image"}


@router.post("/{chat_id}/generate")
async def gen(
    chat_id: int,
    outfit: str = Query(default="default_outfit", description="Ключ из wardrobe (casual, formal, gym, swimwear, sleepwear, underwear, nude)"),
    user: User = Depends(get_current_user)
):
    chat = await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        try:
            if chat.chat_type == "character":
                content = await get_character(chat.target_id)
                character, world = content, None
            else:
                content = await get_world(chat.target_id)
                character, world = None, content

            if not content:
                raise HTTPException(status_code=404, detail="Content not found")

        except Exception as e:
            print(f"Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    messages = await get_chat_history(chat_id)
    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in messages
    ]
    state_meta = chat.state_meta or {}

    nsfw_level = 0
    outfit_key = outfit
    environment = ""
    scene_reasoning = ""
    pose = ""
    scene_description = ""
    if SCENE_ANALYZER_ENABLED and history:
        try:
            llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)
            analyzer = SceneAnalyzer(llm_client)

            visual = content.get("visual", {})
            wardrobe = visual.get("wardrobe", {})
            if not isinstance(wardrobe, dict):
                wardrobe = {}
            available_outfits = ["default_outfit"] + list(wardrobe.keys())

            scene = await analyzer.analyze(
                history=history,
                character_name=content["name"],
                available_outfits=available_outfits
            )

            nsfw_level = scene.nsfw_level
            outfit_key = scene.outfit_key
            pose = scene.pose
            environment = scene.location
            scene_reasoning = scene.reasoning
            scene_description = scene.scene_description

            logging.info(f"Scene analysis: {scene_reasoning}")
            logging.info(f"Scene description: {scene_description}")

        except Exception as e:
            logging.warning(f"Scene analysis failed, using fallback: {e}")
            nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
            outfit_key = outfit
            environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")
    else:
        nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
        environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")

    logging.info(f"{nsfw_level=}")
    environment = chat.current_location or environment
    prompt = Prompt.from_character(
        character=content,
        outfit_key=outfit_key,
        nsfw_level=nsfw_level,
        environment=environment,
    )
    logging.info(f"Chat metrics: affinity={chat.affinity}, arousal={chat.arousal}, location={chat.current_location}")
    prompt.action = state_meta.get("action") or pose
    prompt.scene_details = scene_description
    pos, neg = prompt.build_prompt(content.get("model_type"))
    logging.info(f"{pos=}")
    logging.info(f"{neg=}")
    result = None
    logging.info(f"{content=}")

    if content.get("model_type") == "anime":
        image_url = await submit_anime(pos, neg)

    elif content.get("model_type") == "real":
        image_url = await submit_real(
            prompt=pos,
            allow_nsfw=True,
            nsfw_level=nsfw_level
        )
    else:
        image_url = None
    if image_url:
        try:
            from services.image_storage import download_and_save_image, get_public_url, ImageStorageError

            local_path = None
            file_size = None
            content_type = None
            public_url = image_url 

            try:
                local_path, file_size, content_type = await download_and_save_image(
                    provider_url=image_url,
                    user_id=chat.user_id
                )
                public_url = get_public_url(local_path)
                logging.info(f"Image saved locally: {local_path}")
            except ImageStorageError as e:
                logging.warning(f"Failed to save image locally, using provider URL: {e}")

            await save_generated_image(
                user_id=chat.user_id,
                chat_id=chat.id,
                prompt=pos,
                provider_url=image_url,
                local_path=local_path,
                file_size=file_size,
                content_type=content_type
            )

            if pose:
                current_meta = chat.state_meta or {}
                await update_chat_metrics(
                    chat.id,
                    {"state_meta": {"action": pose, "thought": current_meta.get("thought")}}
                )

            response = {"url": public_url}
            logging.info(f"Returning response: {response}")
            return response

        except Exception as e:
            logging.error(f"Failed to save image or update state: {e}")
            return {"url": image_url}

    response = {"error": "Failed to generate image"}
    logging.info(f"Returning response: {response}")
    return response


@router.post("/generate_preview")
async def generate_char_preview(data: CreateCharacterRequest, user: User = Depends(get_current_user)):
    visual = data.build_visual()
    appearance = visual.get("appearance", "")
    body = visual.get("body", "")
    character_base = f"{appearance}, {body}" if appearance else body

    prompt = Prompt(
        character_base=character_base,
        facial_expression=visual["face"],
        clothing=visual["default_outfit"],
        style=visual.get("style_tags", "")
    )

    pos, neg = prompt.build_prompt(data.style)
    logging.info(f"generate_preview: style={data.style}, pos={pos}, neg={neg}")

    image_url = None
    if data.style == "anime":
        image_url = await submit_anime(pos, neg)
    elif data.style == "real":
        image_url = await submit_real(prompt=pos, allow_nsfw=True)

    if image_url:
        return {"url": image_url}

    raise HTTPException(
        status_code=500,
        detail={
            "error": "generation_failed",
            "message": "Failed to generate image",
            "code": "IMAGE_GEN_FAILED"
        }
    )
