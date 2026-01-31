import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from ...create_character.cc_schemas import CreateCharacterRequest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import APIRouter, HTTPException, Body, Query, Depends, Request

from shared.models import Chat, User
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership
from shared.database import get_session
from shared.database.repositories import MessageRepository, GeneratedImageRepository, ChatRepository
from shared.services.content_loader import get_character, get_world
from shared.services.llm import LLMClient
from shared.services.redis_client import get_redis
from shared.config import SCENE_ANALYZER_ENABLED, SCENE_ANALYZER_MODEL
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
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
    return await data.build_prompt(model_type)

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
                         
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_image_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["images"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    chat = await verify_chat_ownership(chat_id, user)

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
        logging.error(f"Error loading content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    async with get_session() as session:
        message_repo = MessageRepository(session)
        messages = await message_repo.get_history(chat_id)

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
                available_outfits=available_outfits,
                chat_id=chat_id
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
    pos, neg = await prompt.build_prompt(content.get("model_type"))
    logging.info(f"{pos=}")
    logging.info(f"{neg=}")
    logging.info(f"{content=}")

    model_type = content.get("model_type")
    if model_type not in ("anime", "real"):
        raise HTTPException(status_code=400, detail="Unsupported model type")

    task_id = str(uuid4())

    task_params = {
        "chat_id": chat.id,
        "user_id": chat.user_id,
        "model_type": model_type,
        "positive_prompt": pos,
        "negative_prompt": neg,
        "allow_nsfw": True,
        "nsfw_level": nsfw_level,
        "pose": pose,
    }

    redis = await get_redis()
    await redis.set(
        f"task:{task_id}",
        json.dumps({
            "status": "pending",
            "chat_id": chat.id,
            "created_at": datetime.utcnow().isoformat()
        }),
        ex=3600
    )

    try:
        from webapp.main import app
        arq_pool = getattr(app.state, "arq_pool", None)
        if arq_pool:
            await arq_pool.enqueue_job("generate_image_task", task_id, task_params)
            logging.info(f"Task {task_id} enqueued for chat {chat.id}")
        else:
            logging.warning("arq pool not configured, executing synchronously")
            from shared.queue.tasks import generate_image_task
            ctx = {"redis": redis, "get_session": get_session}
            result = await generate_image_task(ctx, task_id, task_params)
            if result.get("status") == "completed":
                return result.get("result", {})
            raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))
    except Exception as e:
        logging.error(f"Failed to enqueue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start generation: {e}")

    response = {"task_id": task_id, "status": "pending"}
    logging.info(f"Returning response: {response}")
    return response

@router.post("/generate_preview")
async def generate_char_preview(data: CreateCharacterRequest, user: User = Depends(get_current_user)):
                         
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_image_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["images"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

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

    pos, neg = await prompt.build_prompt(data.style)
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
