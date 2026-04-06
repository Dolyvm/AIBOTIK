import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4


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
from shared.services.subscription import get_subscription_service
from shared.services.image_provider import generate_image as provider_generate_image
from ..schemas.generate import GenerateRequest, ModelType, Prompt
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
async def build_prompt_endpoint(data: Prompt, model_type: Optional[ModelType] = None, gender: str = "female"):
    return await data.build_prompt(model_type, gender=gender)

@router.post("/generate")
async def generate_image(data: GenerateRequest):
    nsfw_keywords = ["nsfw", "nude", "naked", "explicit", "erotic", "orgasm", "masturbat", "penetrat", "sex"]
    prompt_lower = data.prompt.lower()
    inferred_nsfw = sum(1 for kw in nsfw_keywords if kw in prompt_lower)
    nsfw_level = min(5, inferred_nsfw)

    image_url = await provider_generate_image(
        model_type=data.model_type.value,
        positive_prompt=data.prompt,
        negative_prompt=data.negative_prompt or "",
        allow_nsfw=data.allow_nsfw,
        nsfw_level=nsfw_level,
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

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "images", session)
        if not allowed:
            from shared.database.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("images", limit)

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

        if content.get("visual", {}).get("custom_avatar", False):
            raise HTTPException(status_code=400, detail="Photo generation is not available for this character")

    except HTTPException:
        raise
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
    nsfw_tags = ""
    emotion = "neutral"
    if SCENE_ANALYZER_ENABLED and history:
        try:
            llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)
            analyzer = SceneAnalyzer(llm_client)

            visual = content.get("visual", {})
            wardrobe = visual.get("wardrobe", {})
            if not isinstance(wardrobe, dict):
                wardrobe = {}
            available_outfits = {"default_outfit": visual.get("default_outfit", "")}
            for key, desc in wardrobe.items():
                available_outfits[key] = desc

            allow_nsfw = content.get("is_nsfw", True)

            scene = await analyzer.analyze(
                history=history,
                character_name=content["name"],
                available_outfits=available_outfits,
                allow_nsfw=allow_nsfw,
                chat_id=chat_id,
                mood=chat.current_mood or "neutral",
                affinity=chat.affinity,
                arousal=chat.arousal,
                current_location=chat.current_location or "",
                model_type=content.get("model_type", "anime"),
                gender=content.get("visual", {}).get("gender", "female"),
            )

            nsfw_level = scene.nsfw_level
            outfit_key = scene.outfit_key
            pose = scene.pose
            environment = scene.location
            scene_reasoning = scene.reasoning
            emotion = scene.emotion
            scene_description = scene.scene_description
            nsfw_tags = scene.nsfw_tags

            logging.info(f"Scene analysis: {scene_reasoning}")

        except Exception as e:

            logging.warning(f"Scene analysis failed, using fallback: {e}")
            allow_nsfw = content.get("is_nsfw", True)
            nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
            if not allow_nsfw:
                nsfw_level = min(nsfw_level, 1)
            outfit_key = outfit
            if nsfw_level >= 4:
                outfit_key = "nude"
            elif nsfw_level >= 2:
                outfit_key = "underwear"
            environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")
    else:
        nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
        if nsfw_level >= 4:
            outfit_key = "nude"
        elif nsfw_level >= 2:
            outfit_key = "underwear"
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
    prompt.action = pose or state_meta.get("action", "")
    # scene_description убран из промпта — дублирует environment и перегружает CLIP
    # if scene_description:
    #     prompt.scene_details = scene_description
    if emotion and emotion != "neutral":
        prompt.facial_expression = emotion
    # nsfw_tags — compact context-specific tags from scene analyzer (levels 4-5)
    if nsfw_level >= 4 and nsfw_tags:
        prompt.body_state = nsfw_tags

    logging.info(f"=== PROMPT COMPONENTS for chat {chat_id} ===")
    logging.info(f"  outfit_key={outfit_key}")
    logging.info(f"  clothing={prompt.clothing}")
    logging.info(f"  nsfw_level={nsfw_level}")
    logging.info(f"  scene_description={scene_description}")
    logging.info(f"  nsfw_tags={nsfw_tags}")
    logging.info(f"  emotion={emotion}")
    logging.info(f"  pose/action={prompt.action}")
    logging.info(f"  environment={prompt.environment}")
    logging.info(f"  character_base={prompt.character_base}")
    logging.info(f"  scene_reasoning={scene_reasoning}")
    logging.info(f"=== END COMPONENTS ===")

    char_gender = content.get("visual", {}).get("gender", "female")
    pos, neg = await prompt.build_prompt(content.get("model_type"), gender=char_gender)
    logging.info(f"{pos=}")
    logging.info(f"{neg=}")
    logging.info(f"{content=}")

    model_type = content.get("model_type")
    if model_type not in ("anime", "real"):
        raise HTTPException(status_code=400, detail="Unsupported model type")
    task_id = str(uuid4())

    char_id = (character or {}).get("id") or content.get("name", "")
    seed = int(hashlib.md5(str(char_id).encode()).hexdigest()[:8], 16) % (2**31)

    task_params = {
        "chat_id": chat.id,
        "user_id": chat.user_id,
        "character_id": (character or {}).get("id"),
        "world_id": (world or {}).get("id"),
        "model_type": model_type,
        "positive_prompt": pos,
        "negative_prompt": neg,
        "allow_nsfw": content.get("is_nsfw", True),
        "nsfw_level": nsfw_level,
        "pose": pose,
        "seed": seed,
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
        from main import app
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
                async with get_session() as session:
                    await sub_service.increment_usage(user.telegram_id, "images", session)
                return result.get("result", {})
            raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))
    except Exception as e:
        logging.error(f"Failed to enqueue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start generation: {e}")

    async with get_session() as session:
        await sub_service.increment_usage(user.telegram_id, "images", session)

    response = {"task_id": task_id, "status": "pending"}
    logging.info(f"Returning response: {response}")
    return response

