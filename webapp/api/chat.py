import logging

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import (
    get_session,
    create_chat,
    get_user,
    get_chat_history,
    get_chat_images,
    reset_chat_history,
    add_message,
)
from shared.models import Chat
from shared.services.content_loader import get_character, get_world, get_first_message
from shared.services.llm import LLMClient
from shared.services.context_manager import ContextManager

router = APIRouter(prefix="/api/chat", tags=["chat"])

llm_client = LLMClient()
context_manager = ContextManager(llm_client)


class MessageRequest(BaseModel):
    text: str


class CreateChatRequest(BaseModel):
    user_id: int
    chat_type: str
    target_id: str
    scenario_index: int = 0


@router.get("/{chat_id}/history")
async def get_history(chat_id: int):
    """Получить историю чата (merged: сообщения + картинки)"""
    async with get_session() as session:
        chat = await session.get(Chat, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

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
async def send_message(chat_id: int, payload: MessageRequest = Body(...)):
    """Отправить сообщение и получить ответ"""
    async with get_session() as session:
        try:
            chat = await session.get(Chat, chat_id)

            if not chat:
                raise HTTPException(status_code=404, detail="Chat not found")

            if chat.chat_type == "character":
                content = await get_character(chat.target_id)
                character, world = content, None
            else:
                content = await get_world(chat.target_id)
                character, world = None, content

            if not content:
                raise HTTPException(status_code=404, detail="Content not found")

            user = await get_user(chat.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            user_name = user.username or "User"

            clean_text = await context_manager.process_turn(
                chat=chat,
                user_input=payload.text,
                character=character,
                world=world,
                user_name=user_name,
            )

            return {"response": clean_text}

        except Exception as e:
            logging.error(f"Error in send_message: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_chat_endpoint(payload: CreateChatRequest = Body(...)):
    """Создать новый чат с персонажем/миром"""
    async with get_session() as session:
        try:
            user = await get_user(payload.user_id)
            user_name = user.username if user and user.username else "Путешественник"

            chat = await create_chat(
                user_id=payload.user_id,
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
async def reset_chat(chat_id: int):
    """Сбросить историю чата"""
    async with get_session() as session:
        try:
            chat = await session.get(Chat, chat_id)
            if not chat:
                raise HTTPException(status_code=404, detail="Chat not found")

            await reset_chat_history(chat_id)

            return {"success": True, "message": "Chat history reset"}

        except Exception as e:
            logging.error(f"Error resetting chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))
