import logging

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import (
    get_session,
    create_or_reset_chat,
    get_user,
    update_balance,
    update_chat_full,
)
from shared.models import Chat, User
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
    """Получить историю чата"""
    session = await get_session()
    try:
        chat = await session.get(Chat, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        history = json.loads(chat.history)
        return {
            "history": history,
            "target_id": chat.target_id,
            "type": chat.chat_type,
            "summary": chat.summary or "",
            "msg_count": chat.msg_count
        }
    finally:
        await session.close()


@router.post("/{chat_id}/send")
async def send_message(chat_id: int, payload: MessageRequest = Body(...)):
    """Отправить сообщение и получить ответ"""
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

            user = await get_user(chat.user_id)
            user_name = user.username or "User"

            clean_text, new_state, new_history, new_summary, msgs_since = await context_manager.process_turn(
                chat=chat,
                user_input=payload.text,
                character=character,
                world=world,
                user_name=user_name,
            )

            await update_chat_full(
                chat_id=chat.id,
                history=new_history,
                state=new_state,
                summary=new_summary,
                msgs_since_summary=msgs_since,
                msg_count=chat.msg_count + 1,
            )
            logging.info(new_state)
            return {"response": clean_text}

        except Exception as e:
            print(f"Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_chat(payload: CreateChatRequest = Body(...)):
    """Создать или сбросить чат с персонажем/миром"""
    async with await get_session() as session:
        try:
            user = await get_user(payload.user_id)
            user_name = user.username if user and user.username else "Путешественник"

            chat = await create_or_reset_chat(
                user_id=payload.user_id,
                chat_type=payload.chat_type,
                target_id=payload.target_id,
                scenario_index=payload.scenario_index
            )

            first_message = get_first_message(
                chat_type=payload.chat_type,
                target_id=payload.target_id,
                scenario_index=payload.scenario_index,
                user_name=user_name,
            )

            if first_message:
                chat_obj = await session.get(Chat, chat.id)
                history = [{"role": "assistant", "content": first_message}]
                chat_obj.history = json.dumps(history, ensure_ascii=False)
                await session.commit()

            return {"chat_id": chat.id, "success": True}

        except Exception as e:
            print(f"Error creating chat: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chat_id}/reset")
async def reset_chat(chat_id: int):
    """Сбросить историю чата"""
    session = await get_session()
    try:
        chat = await session.get(Chat, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        chat.history = "[]"
        chat.state = '{"affinity": 0, "arousal": 0, "mood": "neutral"}'
        chat.summary = ""
        chat.msg_count = 0
        chat.msgs_since_summary = 0

        await session.commit()

        return {"success": True, "message": "Chat history reset"}

    except Exception as e:
        print(f"Error resetting chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


