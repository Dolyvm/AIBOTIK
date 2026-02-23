import logging

from fastapi import APIRouter, HTTPException, Body, Depends
from pydantic import BaseModel
import sys
from pathlib import Path

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
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.cache import get_cache

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_display_name(user: User) -> str:
    """Get user display name: nickname > username > fallback."""
    if user.settings and user.settings.nickname:
        return user.settings.nickname
    return user.username or "User"


llm_client = LLMClient()
context_manager = ContextManager(llm_client)

class MessageRequest(BaseModel):
    text: str

class CreateChatRequest(BaseModel):
    chat_type: str
    target_id: str
    scenario_index: int = 0

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

        return {
            "history": all_events,
            "target_id": chat.target_id,
            "type": chat.chat_type,
            "summary": chat.summary or "",
            "affinity": chat.affinity,
            "arousal": chat.arousal,
            "mood": chat.current_mood,
            "location": chat.current_location
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

        result = await context_manager.process_turn(
            chat=chat,
            user_input=payload.text,
            character=character,
            world=world,
            user_name=user_name,
            allow_nsfw=allow_nsfw,
        )

        return {
            "response": result["text"],
            "image_url": result.get("image_url"),
            "nsfw_level": result.get("nsfw_level"),
            "image_task_id": result.get("image_task_id")
        }

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

            if is_new:
                first_message = await get_first_message(
                    chat_type=payload.chat_type,
                    target_id=payload.target_id,
                    scenario_index=payload.scenario_index,
                    user_name=user_name,
                )

                if first_message:
                    await message_repo.add(chat.id, "assistant", first_message)

            return {"chat_id": chat.id, "success": True}

        except Exception as e:
            logging.error(f"Error creating chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/{chat_id}/reset")
async def reset_chat(chat_id: int, user: User = Depends(get_current_user)):
    await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        try:
            user_name = _get_display_name(user)

            chat_repo = ChatRepository(session)
            message_repo = MessageRepository(session)

            await chat_repo.reset_history(chat_id)

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

        return {
            "player_message": result["player_message"],
            "character_response": result["character_response"],
            "image_url": result.get("image_url"),
            "nsfw_level": result.get("nsfw_level"),
            "image_task_id": result.get("image_task_id"),
            "affinity": result["affinity"],
            "arousal": result["arousal"],
            "mood": chat.current_mood,
            "location": chat.current_location
        }

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

        return {
            "player_message": result["player_message"]
        }

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

        # Удалить GeneratedImages, созданные после отправки user-сообщения
        await session.execute(
            sa_delete(GeneratedImage)
            .where(GeneratedImage.chat_id == chat_id)
            .where(GeneratedImage.created_at >= user_msg_created_at)
        )
        await session.commit()

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
        chat_repo = ChatRepository(session)
        await chat_repo.delete(chat_id)

    cache = get_cache()
    if cache:
        await cache.invalidate_chat_state(chat_id)

    return {"success": True}
