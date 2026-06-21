import datetime
import json
import logging

from fastapi import APIRouter, HTTPException, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import sys
from pathlib import Path

from shared.services.analytics import AnalyticsService

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.database import get_session
from shared.database.repositories import (
    ChatRepository,
    MessageRepository,
    GeneratedImageRepository,
    ImageGenerationJobRepository,
)
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from shared.models import Chat, User, GeneratedImage
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership
from shared.services.content_loader import get_character, get_world, get_first_message
from shared.services.llm import LLMClient
from shared.services.context_manager import ContextManager
from shared.config import ADMIN_TELEGRAM_IDS, CHAT_MODEL
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.subscription import get_subscription_service
from shared.database.exceptions import UsageLimitExceeded
from shared.services.cache import get_cache
from shared.services.image_cleanup import collect_chat_image_paths, collect_images_since, delete_files
from shared.services import facefusion_provider, manhwa_provider
from shared.services.runpod_job_registry import cancel_recorded_runpod_jobs

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_display_name(user: User) -> str:
    """Get user display name: nickname > username > fallback."""
    if user.settings and user.settings.nickname:
        return user.settings.nickname
    return user.username or "User"


llm_client = LLMClient(
    model=CHAT_MODEL,
    provider={"sort": "throughput"},
    reasoning={"enabled": False},
)
context_manager = ContextManager(llm_client)


class MessageRequest(BaseModel):
    text: str


class CreateChatRequest(BaseModel):
    chat_type: str
    target_id: str
    scenario_index: int = 0


def _scenario_heat_level(content: dict | None, scenario_index: int) -> int:
    if not content:
        return 0
    for scenario in content.get("scenarios_full", []):
        if scenario.get("index") == scenario_index:
            return scenario.get("heat_level", 0)
    return 0


async def _sync_existing_chat_to_scenario_heat(
    chat: Chat,
    scenario_heat: int,
    chat_repo: ChatRepository,
    message_repo: MessageRepository,
) -> None:
    from shared.constants import HEAT_LEVEL_DEFAULTS, get_heat_level, normalize_heat_level

    scenario_heat = normalize_heat_level(scenario_heat)
    current_heat = get_heat_level(chat)
    if scenario_heat >= current_heat:
        return

    messages = await message_repo.get_history(chat.id)
    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in messages
    ]
    if len(history) > 4:
        return

    defaults = HEAT_LEVEL_DEFAULTS.get(scenario_heat, HEAT_LEVEL_DEFAULTS[0])
    state_meta = dict(chat.state_meta or {})
    state_meta["heat_level"] = scenario_heat
    await chat_repo.update_metrics(chat.id, {
        "affinity": defaults["affinity"],
        "arousal": defaults["arousal"],
        "state_meta": state_meta,
    })
    chat.affinity = defaults["affinity"]
    chat.arousal = defaults["arousal"]
    chat.state_meta = state_meta


async def _cancel_active_image_job_for_chat(job_repo: ImageGenerationJobRepository, chat_id: int, reason: str) -> None:
    active_job = await job_repo.get_active_for_chat(chat_id)
    if not active_job:
        return
    await cancel_recorded_runpod_jobs(active_job.request_payload, reason=reason)
    await job_repo.mark_canceled(active_job.id)


def _stream_event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload}, ensure_ascii=False) + "\n"


def _image_event(image: GeneratedImage) -> dict:
    return {
        "role": "assistant",
        "image_id": image.id,
        "avatar": image.public_url,
        "timestamp": image.created_at.isoformat(),
    }


def _is_admin_user(user: User) -> bool:
    return getattr(user, "telegram_id", None) in ADMIN_TELEGRAM_IDS


def _debug_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _markdown_code_block(label: str, text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"**{label}**\n{fence}\n{text}\n{fence}"


def _photo_prompt_debug_event(image: GeneratedImage) -> dict | None:
    metadata = image.prompt_metadata or {}
    replicate_input = metadata.get("replicate_input") if isinstance(metadata, dict) else {}
    if not isinstance(replicate_input, dict):
        replicate_input = {}

    provider_prompt = _debug_text(
        metadata.get("provider_prompt")
        or replicate_input.get("prompt")
        or metadata.get("positive_prompt")
        or image.prompt
    )
    if not provider_prompt:
        return None

    negative_prompt = _debug_text(
        metadata.get("provider_negative_prompt")
        or replicate_input.get("negative_prompt")
        or metadata.get("negative_prompt")
    )
    provider = _debug_text(metadata.get("provider") or metadata.get("runpod_provider") or "unknown")
    model = _debug_text(metadata.get("replicate_model") or metadata.get("provider_model"))

    lines = [
        "Photo prompt debug",
        f"Provider: `{provider}`",
    ]
    if model:
        lines.append(f"Model: `{model}`")
    lines.extend(["", _markdown_code_block("Positive", provider_prompt)])
    if negative_prompt:
        lines.extend(["", _markdown_code_block("Negative", negative_prompt)])

    return {
        "role": "assistant",
        "type": "photo_prompt_debug",
        "debug_for_image_id": image.id,
        "content": "\n".join(lines),
        "timestamp": image.created_at.isoformat(),
    }


def _image_events(image: GeneratedImage, *, include_debug: bool = False) -> list[dict]:
    events = [_image_event(image)]
    if include_debug:
        debug_event = _photo_prompt_debug_event(image)
        if debug_event:
            events.append(debug_event)
    return events


def _job_status_payload(
    job,
    image: GeneratedImage | None = None,
    *,
    include_debug: bool = False,
) -> dict:
    payload = {
        "job_id": job.id,
        "status": job.status,
    }
    if image:
        payload["image"] = _image_event(image)
        if include_debug:
            debug_event = _photo_prompt_debug_event(image)
            if debug_event:
                payload["debug_messages"] = [debug_event]
    if job.status in {"failed", "canceled"}:
        payload["message"] = job.error_message or (
            "Генерация отменена" if job.status == "canceled" else "Ошибка генерации фото"
        )
    return payload


def _photo_capabilities_for_character(character: dict | None) -> dict:
    visual = (character or {}).get("visual") or {}
    model_type = (character or {}).get("model_type") or visual.get("model_type")
    custom_avatar = bool(visual.get("custom_avatar"))
    identity_reference = visual.get("identity_reference") or {}
    face_swap_available = (
        custom_avatar
        and identity_reference.get("status") == "ready"
        and facefusion_provider.is_configured()
    )
    manhwa_available = model_type == "manhwa" and manhwa_provider.is_configured()
    available = bool(character)
    if custom_avatar:
        available = available and face_swap_available
    if model_type == "manhwa":
        available = available and manhwa_available
    return {
        "available": available,
        "mode": "identity_facefusion" if custom_avatar else "standard",
        "custom_avatar": custom_avatar,
        "face_swap_available": face_swap_available,
        "manhwa_available": manhwa_available,
    }


def _chat_photo_usage_type(character: dict | None) -> str:
    visual = (character or {}).get("visual") or {}
    if visual.get("custom_avatar"):
        return "avatar_generations"
    return "images_generated"


def _message_snapshot(messages) -> list[dict]:
    return [
        {
            "role": getattr(msg.role, "value", msg.role),
            "content": msg.content,
        }
        for msg in messages
    ]


@router.get("/{chat_id}/history")
async def get_history(chat_id: int, user: User = Depends(get_current_user)):
    chat = await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        message_repo = MessageRepository(session)
        image_repo = GeneratedImageRepository(session)
        job_repo = ImageGenerationJobRepository(session)

        messages = await message_repo.get_history(chat_id)
        images = await image_repo.get_by_chat(chat_id)
        active_image_job = await job_repo.get_active_for_chat(chat_id)
        character_data = await get_character(chat.target_id) if chat.chat_type == "character" else None
        photo_capabilities = (
            _photo_capabilities_for_character(character_data)
            if chat.chat_type == "character"
            else {
                "available": False,
                "mode": "unavailable",
                "custom_avatar": False,
                "face_swap_available": False,
                "manhwa_available": False,
            }
        )

        msg_dicts = [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat()
            }
            for msg in messages
        ]
        image_events = [
            event
            for image in images
            for event in _image_events(image, include_debug=_is_admin_user(user))
        ]

        all_events = msg_dicts + image_events
        all_events.sort(key=lambda x: x["timestamp"])

        return {
            "history": all_events,
            "target_id": chat.target_id,
            "type": chat.chat_type,
            "summary": chat.summary or "",
            "affinity": chat.affinity,
            "arousal": chat.arousal,
            "mood": chat.current_mood,
            "location": chat.current_location,
            "active_image_job": (
                _job_status_payload(active_image_job) if active_image_job else None
            ),
            "photo_capabilities": photo_capabilities,
            "custom_avatar": photo_capabilities["custom_avatar"],
            "photo_generation_available": photo_capabilities["available"],
            "photo_generation_mode": photo_capabilities["mode"],
            "photo_prompt_debug_available": _is_admin_user(user),
        }


@router.post("/{chat_id}/send")
async def send_message(chat_id: int, payload: MessageRequest = Body(...), user: User = Depends(get_current_user)):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_llm_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["llm"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    chat = await verify_chat_ownership(chat_id, user)

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "messages", session)
        if not allowed:
            raise UsageLimitExceeded("messages", limit)

    try:
        if chat.chat_type == "character":
            content = await get_character(chat.target_id)
            character, world = content, None
        else:
            content = await get_world(chat.target_id)
            character, world = None, content

        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

        user_name = _get_display_name(user)

        allow_nsfw = character.get("is_nsfw", True) if character else True

        async def stream_response():
            try:
                async for chunk in context_manager.process_turn_stream(
                    chat=chat,
                    user_input=payload.text,
                    character=character,
                    world=world,
                    user_name=user_name,
                    allow_nsfw=allow_nsfw,
                ):
                    if chunk:
                        yield _stream_event("chunk", content=chunk)

                async with get_session() as session:
                    await sub_service.increment_usage(user.telegram_id, "messages", session)

                async with get_session() as session:
                    await AnalyticsService.track(
                        session,
                        user_id=user.telegram_id,
                        event_type="message_sent",
                        entity_type="chats",
                        entity_id=str(chat.id),
                        meta={
                            "character_id": character.get("id") if character else None,
                            "world_id": world.get("id") if world else None,
                            "message_length": len(payload.text),
                        }
                    )

                yield _stream_event("done")
            except Exception as e:
                logging.exception("Error in send_message stream: chat_id=%s error=%s", chat.id, e)
                yield _stream_event(
                    "error",
                    code="llm_generation_failed",
                    message="Ошибка генерации LLM",
                )

        return StreamingResponse(
            stream_response(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except (UsageLimitExceeded, HTTPException):
        raise
    except Exception as e:
        logging.error(f"Error in send_message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chat_id}/generate-image")
async def generate_image(
    chat_id: int,
    request: Request,
    user: User = Depends(get_current_user),
):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_api_rate_limit(
            endpoint="chat_image_generation",
            telegram_id=user.telegram_id,
        )
        if not allowed:
            limits = RATE_LIMITS["chat_image_generation"]
            raise RateLimitExceeded(
                limit=limits["limit"],
                window=limits["window"],
                retry_after=limits["retry_after"],
            )

    chat = await verify_chat_ownership(chat_id, user)
    if chat.chat_type != "character":
        raise HTTPException(status_code=400, detail="Фото можно генерировать только в чате с персонажем")

    async with get_session() as session:
        job_repo = ImageGenerationJobRepository(session)
        active_job = await job_repo.get_active_for_chat(chat.id)
        if active_job:
            return JSONResponse(
                status_code=202,
                content=_job_status_payload(active_job),
            )

    arq_pool = getattr(request.app.state, "arq_pool", None)
    if not arq_pool:
        raise HTTPException(status_code=503, detail="Генерация фото временно недоступна")

    character = await get_character(chat.target_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    photo_capabilities = _photo_capabilities_for_character(character)
    if not photo_capabilities["available"]:
        raise HTTPException(status_code=503, detail="Генерация фото для этого персонажа временно недоступна")

    usage_type = _chat_photo_usage_type(character)
    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(
            user.telegram_id,
            usage_type,
            session,
        )
        if not allowed:
            raise UsageLimitExceeded(usage_type, limit)

    async with get_session() as session:
        message_repo = MessageRepository(session)
        recent_messages = await message_repo.get_history(chat.id, limit=5)

    request_payload = {
        "character": character,
        "recent_messages": _message_snapshot(recent_messages),
        "chat_state": dict(chat.state_meta or {}),
    }

    async with get_session() as session:
        job_repo = ImageGenerationJobRepository(session)
        try:
            job = await job_repo.create_job(
                user_id=user.telegram_id,
                chat_id=chat.id,
                request_payload=request_payload,
            )
        except IntegrityError:
            await session.rollback()
            active_job = await job_repo.get_active_for_chat(chat.id)
            if active_job:
                return JSONResponse(
                    status_code=202,
                    content=_job_status_payload(active_job),
                )
            raise

        arq_job_id = f"chat-image-generation:{job.id}"
        try:
            enqueued_job = await arq_pool.enqueue_job(
                "generate_chat_image_task",
                job.id,
                _job_id=arq_job_id,
            )
        except Exception as e:
            logging.exception("Failed to enqueue image generation job: job_id=%s error=%s", job.id, e)
            await job_repo.mark_failed(
                job.id,
                "queue_unavailable",
                "Генерация фото временно недоступна",
            )
            raise HTTPException(status_code=503, detail="Генерация фото временно недоступна")

        await job_repo.set_arq_job_id(job.id, getattr(enqueued_job, "job_id", arq_job_id))
        return JSONResponse(
            status_code=202,
            content=_job_status_payload(job),
        )


@router.get("/{chat_id}/image-jobs/{job_id}")
async def get_image_generation_job(
    chat_id: int,
    job_id: int,
    user: User = Depends(get_current_user),
):
    await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        job_repo = ImageGenerationJobRepository(session)
        job = await job_repo.get_by_chat_and_id(chat_id, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Image generation job not found")

        image = await session.get(GeneratedImage, job.image_id) if job.image_id else None
        return _job_status_payload(job, image, include_debug=_is_admin_user(user))


@router.get("/by-character/{target_id}")
async def get_chats_for_character(target_id: str, chat_type: str, user: User = Depends(get_current_user)):
    """Return existing chats for a given character/world (one per scenario_index)."""
    async with get_session() as session:
        chat_repo = ChatRepository(session)
        chats = await chat_repo.get_chats_for_target(user.telegram_id, target_id, chat_type)
        return [{"chat_id": c.id, "scenario_index": c.scenario_index} for c in chats]


@router.post("/create")
async def create_chat_endpoint(payload: CreateChatRequest = Body(...), user: User = Depends(get_current_user)):
    async with get_session() as session:
        try:
            user_name = _get_display_name(user)

            chat_repo = ChatRepository(session)
            message_repo = MessageRepository(session)

            chat, is_new = await chat_repo.create_chat(
                user_id=user.telegram_id,
                chat_type=payload.chat_type,
                target_id=payload.target_id,
                scenario_index=payload.scenario_index
            )

            content = None
            if payload.chat_type == "character":
                content = await get_character(payload.target_id)

            if is_new:
                # Apply heat_level initial state
                heat_level = _scenario_heat_level(content, payload.scenario_index)

                from shared.constants import HEAT_LEVEL_DEFAULTS, normalize_heat_level
                heat_level = normalize_heat_level(heat_level)
                defaults = HEAT_LEVEL_DEFAULTS.get(heat_level, HEAT_LEVEL_DEFAULTS[0])
                await chat_repo.update_metrics(chat.id, {
                    "affinity": defaults["affinity"],
                    "arousal": defaults["arousal"],
                    "state_meta": {"heat_level": heat_level},
                })
                chat.affinity = defaults["affinity"]
                chat.arousal = defaults["arousal"]
                chat.state_meta = {"heat_level": heat_level}

                first_message = await get_first_message(
                    chat_type=payload.chat_type,
                    target_id=payload.target_id,
                    scenario_index=payload.scenario_index,
                    user_name=user_name,
                )

                if first_message:
                    await message_repo.add(chat.id, "assistant", first_message)

                if not user.first_interaction_at:
                    user.first_interaction_at = datetime.datetime.now()
                await AnalyticsService.track(
                    session,
                    user_id=user.telegram_id,
                    event_type="character_chat_started",
                    entity_type=payload.chat_type,
                    entity_id=str(payload.target_id),
                    meta={
                        "chat_type": payload.chat_type,
                        "chat_id": chat.id,
                        "scenario_index": payload.scenario_index
                        }
                    )
            elif payload.chat_type == "character":
                await _sync_existing_chat_to_scenario_heat(
                    chat,
                    _scenario_heat_level(content, payload.scenario_index),
                    chat_repo,
                    message_repo,
                )

            return {"chat_id": chat.id, "success": True}

        except Exception as e:
            logging.error(f"Error creating chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chat_id}/reset")
async def reset_chat(chat_id: int, user: User = Depends(get_current_user)):
    verified_chat = await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        try:
            user_name = _get_display_name(user)

            chat_repo = ChatRepository(session)
            message_repo = MessageRepository(session)
            job_repo = ImageGenerationJobRepository(session)

            paths = await collect_chat_image_paths(session, chat_id)
            scenario_heat = 0
            if verified_chat.chat_type == "character":
                content = await get_character(verified_chat.target_id)
                scenario_heat = _scenario_heat_level(content, verified_chat.scenario_index or 0)

            await _cancel_active_image_job_for_chat(job_repo, chat_id, "chat_reset")
            await chat_repo.reset_history(chat_id, heat_level=scenario_heat)

            delete_files(paths)

            chat = await chat_repo.get_by_id(chat_id)

            first_message = await get_first_message(
                chat_type=chat.chat_type,
                target_id=chat.target_id,
                scenario_index=chat.scenario_index,
                user_name=user_name,
            )

            if first_message:
                await message_repo.add(chat.id, "assistant", first_message)

            return {"success": True, "message": "Chat reset", "first_message": first_message}

        except Exception as e:
            logging.error(f"Error resetting chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chat_id}/auto-continue")
async def auto_continue_dialogue(chat_id: int, user: User = Depends(get_current_user)):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_api_rate_limit(
            endpoint="chat_auto_continue",
            telegram_id=user.telegram_id
        )
        if not allowed:
            limits = RATE_LIMITS["chat_auto_continue"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    chat = await verify_chat_ownership(chat_id, user)

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "messages", session)
        if not allowed:
            raise UsageLimitExceeded("messages", limit)

    try:
        if chat.chat_type == "character":
            content = await get_character(chat.target_id)
            character, world = content, None
        else:
            content = await get_world(chat.target_id)
            character, world = None, content

        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

        user_name = _get_display_name(user)

        allow_nsfw = character.get("is_nsfw", True) if character else True

        result = await context_manager.auto_reply_cycle(
            chat=chat,
            character=character,
            world=world,
            user_name=user_name,
            allow_nsfw=allow_nsfw
        )

        async with get_session() as session:
            await sub_service.increment_usage(user.telegram_id, "messages", session)

        return {
            "player_message": result["player_message"],
            "character_response": result["character_response"],
            "affinity": result["affinity"],
            "arousal": result["arousal"],
            "mood": chat.current_mood,
            "location": chat.current_location
        }

    except (UsageLimitExceeded, HTTPException):
        raise
    except Exception as e:
        logging.error(f"Error in auto_continue_dialogue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chat_id}/generate-auto-reply")
async def generate_auto_reply(chat_id: int, user: User = Depends(get_current_user)):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_api_rate_limit(
            endpoint="chat_auto_continue",
            telegram_id=user.telegram_id
        )
        if not allowed:
            limits = RATE_LIMITS["chat_auto_continue"]
            raise RateLimitExceeded(limit=limits["limit"], window=limits["window"], retry_after=limits["retry_after"])

    chat = await verify_chat_ownership(chat_id, user)

    sub_service = get_subscription_service()
    async with get_session() as session:
        allowed, remaining, limit = await sub_service.check_usage_allowed(user.telegram_id, "messages", session)
        if not allowed:
            raise UsageLimitExceeded("messages", limit)

    try:
        if chat.chat_type == "character":
            content = await get_character(chat.target_id)
            character, world = content, None
        else:
            content = await get_world(chat.target_id)
            character, world = None, content

        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

        user_name = _get_display_name(user)

        result = await context_manager.auto_reply_cycle(
            chat=chat,
            character=character,
            world=world,
            user_name=user_name,
            only_user_reply=True
        )

        async with get_session() as session:
            await sub_service.increment_usage(user.telegram_id, "messages", session)

        return {
            "player_message": result["player_message"]
        }

    except (UsageLimitExceeded, HTTPException):
        raise
    except Exception as e:
        logging.error(f"Error in auto_continue_dialogue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{chat_id}/undo")
async def undo_last_turn(chat_id: int, user: User = Depends(get_current_user)):
    """Удаляет последнюю пару сообщений (user + assistant) и прикреплённые фото."""
    await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        message_repo = MessageRepository(session)
        job_repo = ImageGenerationJobRepository(session)

        try:
            deleted, user_msg_created_at = await message_repo.delete_last_pair(chat_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        await _cancel_active_image_job_for_chat(job_repo, chat_id, "chat_undo")
        paths = await collect_images_since(session, chat_id, user_msg_created_at)

        # Удалить GeneratedImages, созданные после отправки user-сообщения
        await session.execute(
            sa_delete(GeneratedImage)
            .where(GeneratedImage.chat_id == chat_id)
            .where(GeneratedImage.created_at >= user_msg_created_at)
        )
        await session.commit()

    delete_files(paths)

    cache = get_cache()
    if cache:
        await cache.invalidate_chat_state(chat_id)

    return {"success": True, "deleted": deleted}


@router.delete("/{chat_id}")
async def delete_chat(
        chat_id: int,
        user: User = Depends(get_current_user)
):
    """Delete a chat and all its messages/images."""
    await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        paths = await collect_chat_image_paths(session, chat_id)

        job_repo = ImageGenerationJobRepository(session)
        await _cancel_active_image_job_for_chat(job_repo, chat_id, "chat_delete")

        chat_repo = ChatRepository(session)
        await chat_repo.delete(chat_id)

    delete_files(paths)

    cache = get_cache()
    if cache:
        await cache.invalidate_chat_state(chat_id)

    return {"success": True}
