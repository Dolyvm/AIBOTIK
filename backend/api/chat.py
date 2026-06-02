import datetime
import json
import logging

from fastapi import APIRouter, HTTPException, Body, Depends
from fastapi.responses import StreamingResponse
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
    GeneratedImageRepository
)
from sqlalchemy import delete as sa_delete
from shared.models import Chat, User, GeneratedImage
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership
from shared.services.content_loader import get_character, get_world, get_first_message
from shared.services.llm import LLMClient
from shared.services.context_manager import ContextManager
from shared.config import CHAT_MODEL, LLM_CHAT_PROVIDER_ROUTING
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.subscription import get_subscription_service
from shared.database.exceptions import UsageLimitExceeded
from shared.services.cache import get_cache
from shared.services.image_cleanup import collect_chat_image_paths, collect_images_since, delete_files

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_display_name(user: User) -> str:
    """Get user display name: nickname > username > fallback."""
    if user.settings and user.settings.nickname:
        return user.settings.nickname
    return user.username or "User"


llm_client = LLMClient(
    model=CHAT_MODEL,
    provider=LLM_CHAT_PROVIDER_ROUTING,
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
    from api.image_gen.services.scene_analyzer import has_explicit_nude_or_sex_context

    scenario_heat = normalize_heat_level(scenario_heat)
    current_heat = get_heat_level(chat)
    if scenario_heat >= current_heat:
        return

    messages = await message_repo.get_history(chat.id)
    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in messages
    ]
    if len(history) > 4 or has_explicit_nude_or_sex_context(history):
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


def _stream_event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload}, ensure_ascii=False) + "\n"


@router.get("/{chat_id}/history")
async def get_history(chat_id: int, user: User = Depends(get_current_user)):
    chat = await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        message_repo = MessageRepository(session)
        image_repo = GeneratedImageRepository(session)

        messages = await message_repo.get_history(chat_id)
        images = await image_repo.get_by_chat_formatted(chat_id)

        msg_dicts = [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat()
            }
            for msg in messages
        ]

        all_events = msg_dicts + images
        all_events.sort(key=lambda x: x["timestamp"])

        custom_avatar = False
        photo_generation_available = chat.chat_type == "character"
        photo_generation_mode = "standard" if chat.chat_type == "character" else "unavailable"
        if chat.chat_type == "character":
            from shared.services.content_loader import get_character
            char_data = await get_character(chat.target_id)
            if char_data:
                visual = char_data.get("visual", {})
                custom_avatar = visual.get("custom_avatar", False)
                identity_reference = visual.get("identity_reference") or {}
                if custom_avatar:
                    photo_generation_available = True
                    photo_generation_mode = (
                        "identity_facefusion"
                        if identity_reference.get("status") == "ready"
                        else "identity_facefusion"
                    )

        return {
            "history": all_events,
            "target_id": chat.target_id,
            "type": chat.chat_type,
            "summary": chat.summary or "",
            "affinity": chat.affinity,
            "arousal": chat.arousal,
            "mood": chat.current_mood,
            "location": chat.current_location,
            "custom_avatar": custom_avatar,
            "photo_generation_available": photo_generation_available,
            "photo_generation_mode": photo_generation_mode,
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

            paths = await collect_chat_image_paths(session, chat_id)
            scenario_heat = 0
            if verified_chat.chat_type == "character":
                content = await get_character(verified_chat.target_id)
                scenario_heat = _scenario_heat_level(content, verified_chat.scenario_index or 0)

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
        try:
            deleted, user_msg_created_at = await message_repo.delete_last_pair(chat_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

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

        chat_repo = ChatRepository(session)
        await chat_repo.delete(chat_id)

    delete_files(paths)

    cache = get_cache()
    if cache:
        await cache.invalidate_chat_state(chat_id)

    return {"success": True}
