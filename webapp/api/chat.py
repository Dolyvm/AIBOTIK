import logging

from fastapi import APIRouter, HTTPException, Body, Depends
from pydantic import BaseModel
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.repository import (
    get_session,
    create_chat,
    get_user,
    get_chat_history,
    get_chat_images,
    reset_chat_history,
    add_message,
)
from shared.models import Chat, User
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership
from shared.services.content_loader import get_character, get_world, get_first_message
from shared.services.llm import LLMClient
from shared.services.context_manager import ContextManager

router = APIRouter(prefix="/api/chat", tags=["chat"])

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
    """Получить историю чата (merged: сообщения + картинки)"""
    chat = await verify_chat_ownership(chat_id, user)

    async with get_session() as session:

        messages = await get_chat_history(chat_id)
        images = await get_chat_images(chat_id)

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
    """Отправить сообщение и получить ответ"""
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

            user_name = user.username or "User"

            result = await context_manager.process_turn(
                chat=chat,
                user_input=payload.text,
                character=character,
                world=world,
                user_name=user_name,
            )

            return {
                "response": result["text"],
                "image_url": result.get("image_url")
            }

        except Exception as e:
            logging.error(f"Error in send_message: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_chat_endpoint(payload: CreateChatRequest = Body(...), user: User = Depends(get_current_user)):
    """Создать новый чат с персонажем/миром"""
    async with get_session() as session:
        try:
            user_name = user.username if user.username else "Путешественник"

            chat = await create_chat(
                user_id=user.telegram_id,
                chat_type=payload.chat_type,
                target_id=payload.target_id,
                scenario_index=payload.scenario_index
            )

            first_message = await get_first_message(
                chat_type=payload.chat_type,
                target_id=payload.target_id,
                scenario_index=payload.scenario_index,
                user_name=user_name,
            )

            if first_message:
                await add_message(chat.id, "assistant", first_message)

            return {"chat_id": chat.id, "success": True}

        except Exception as e:
            logging.error(f"Error creating chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chat_id}/reset")
async def reset_chat(chat_id: int, user: User = Depends(get_current_user)):
    """Сбросить историю чата"""
    chat = await verify_chat_ownership(chat_id, user)

    async with get_session() as session:
        try:
            await reset_chat_history(chat_id)

            return {"success": True, "message": "Chat history reset"}

        except Exception as e:
            logging.error(f"Error resetting chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/{chat_id}/auto-continue")
async def auto_continue_dialogue(chat_id: int, user: User = Depends(get_current_user)):
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

        user_name = user.username or "User"

        result = await context_manager.auto_reply_cycle(
            chat=chat,
            character=character,
            world=world,
            user_name=user_name
        )

        return {
            "player_message": result["player_message"],
            "character_response": result["character_response"],
            "image_url": result.get("image_url"),
            "affinity": result["affinity"],
            "arousal": result["arousal"],
            "mood": chat.current_mood,
            "location": chat.current_location
        }

    except Exception as e:
        logging.error(f"Error in auto_continue_dialogue: {e}")
        raise HTTPException(status_code=500, detail=str(e))