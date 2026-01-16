from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import get_session, create_or_reset_chat, get_user, update_balance
from shared.models import Chat, User
from shared.card_parser import get_character
from services.chat_logic import generate_response
from bot.services.imagegen import ImageGenerator

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Initialize ImageGenerator
MODELSLAB_API_KEY = os.getenv("MODELSLAB_API_KEY", "")
FAL_KEY = os.getenv("FAL_KEY", "")
image_generator = ImageGenerator(api_key=MODELSLAB_API_KEY, fal_key=FAL_KEY)


class MessageRequest(BaseModel):
    text: str


class CreateChatRequest(BaseModel):
    user_id: int
    chat_type: str  # "character" or "world"
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
        return {"history": history, "target_id": chat.target_id, "type": chat.chat_type}
    finally:
        await session.close()


@router.post("/{chat_id}/send")
async def send_message(chat_id: int, payload: MessageRequest = Body(...)):
    """Отправить сообщение и получить ответ"""
    session = await get_session()
    try:
        chat = await session.get(Chat, chat_id)

        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Генерация ответа
        ai_text, new_history = await generate_response(chat, payload.text)

        # Сохранение в БД
        chat.history = json.dumps(new_history, ensure_ascii=False)
        chat.msg_count += 1
        await session.commit()

        return {"response": ai_text}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


def replace_placeholders(text: str, user_name: str, char_name: str) -> str:
    """Заменяет плейсхолдеры {{user}} и {{char}} в тексте"""
    if not text:
        return text
    return text.replace("{{user}}", user_name).replace("{{char}}", char_name)


@router.post("/create")
async def create_chat(payload: CreateChatRequest = Body(...)):
    """Создать или сбросить чат с персонажем/миром"""
    session = await get_session()
    try:
        # Получаем имя пользователя из БД
        user = await get_user(payload.user_id)
        user_name = user.username if user and user.username else "Путешественник"

        chat = await create_or_reset_chat(
            user_id=payload.user_id,
            chat_type=payload.chat_type,
            target_id=payload.target_id,
            scenario_index=payload.scenario_index
        )

        # Добавляем первое сообщение от персонажа/мира
        first_message = None

        if payload.chat_type == "character":
            character = get_character(Path("/app/content/characters"), payload.target_id)
            if character:
                char_name = character.get("name", "")

                # Берем alternate_greetings[scenario_index] или first_mes
                if payload.scenario_index > 0 and character.get("alternate_greetings"):
                    greetings = character["alternate_greetings"]
                    if payload.scenario_index - 1 < len(greetings):
                        first_message = greetings[payload.scenario_index - 1]

                # Если нет alternate_greeting, берем first_mes
                if not first_message:
                    first_message = character.get("first_mes", "")

                # Заменяем плейсхолдеры
                first_message = replace_placeholders(first_message, user_name, char_name)

        else:  # world
            world_path = Path("/app/content/worlds") / f"{payload.target_id}.json"
            if world_path.exists():
                with open(world_path) as f:
                    world = json.load(f)

                    # Select intro based on scenario_index
                    if payload.scenario_index > 0 and world.get("alternate_scenarios"):
                        scenarios = world["alternate_scenarios"]
                        if payload.scenario_index - 1 < len(scenarios):
                            first_message = scenarios[payload.scenario_index - 1].get("intro", "")

                    # Default to main intro_message
                    if not first_message:
                        first_message = world.get("intro_message", "")

                    # Для миров заменяем только {{user}}
                    first_message = replace_placeholders(first_message, user_name, "")

        # Обновляем историю чата с первым сообщением
        if first_message:
            chat_obj = await session.get(Chat, chat.id)
            history = [{"role": "assistant", "content": first_message}]
            chat_obj.history = json.dumps(history, ensure_ascii=False)
            await session.commit()

        return {"chat_id": chat.id, "success": True}

    except Exception as e:
        print(f"Error creating chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/{chat_id}/reset")
async def reset_chat(chat_id: int):
    """Сбросить историю чата"""
    session = await get_session()
    try:
        chat = await session.get(Chat, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Сбрасываем историю и состояние
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


@router.post("/{chat_id}/photo")
async def generate_photo(chat_id: int):
    """
    Generate a photo based on current scenario and arousal level.
    Costs 50 tokens per generation.
    """
    session = await get_session()
    try:
        # Fetch chat from database
        chat = await session.get(Chat, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Only support character chats
        if chat.chat_type != "character":
            raise HTTPException(status_code=400, detail="Photo generation only available for character chats")

        # Fetch user
        user = await session.get(User, chat.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Check balance
        PHOTO_COST = 50
        if user.balance < PHOTO_COST:
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient balance. Need {PHOTO_COST} tokens, have {user.balance}"
            )

        # Parse chat state to get arousal
        try:
            state = json.loads(chat.state)
            arousal = state.get("arousal", 0)
        except:
            arousal = 0

        # Get scenario index
        scenario_index = chat.scenario_index or 0

        # Generate image
        try:
            image_url = await image_generator.generate(
                character_id=chat.target_id,
                scenario_index=scenario_index,
                arousal=arousal
            )
        except Exception as e:
            print(f"Image generation error: {e}")
            raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

        # Deduct tokens
        user.balance -= PHOTO_COST

        # Add image to chat history as assistant message
        history = json.loads(chat.history)
        history.append({
            "role": "assistant",
            "content": f"![Generated Photo]({image_url})"
        })
        chat.history = json.dumps(history, ensure_ascii=False)

        await session.commit()

        return {
            "success": True,
            "image_url": image_url,
            "remaining_balance": user.balance,
            "cost": PHOTO_COST
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating photo: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()
