from aiogram import Router, F
from aiogram.types import Message
import json
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import create_or_reset_chat, update_chat_history
from shared.services.content_loader import get_character, get_world, get_first_message

router = Router()


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    data = json.loads(message.web_app_data.data)
    user_id = message.from_user.id

    if data.get("action") == "start_chat":
        chat = await create_or_reset_chat(
            user_id=user_id,
            chat_type=data["type"],
            target_id=data["id"],
            scenario_index=data.get("scenario", 0)
        )

        greeting = get_first_message(
            chat_type=data["type"],
            target_id=data["id"],
            scenario_index=data.get("scenario", 0),
            user_name=message.from_user.first_name,
        )

        if not greeting:
            await message.answer("❌ Контент не найден")
            return

        history = [{"role": "assistant", "content": greeting}]
        await update_chat_history(chat.id, history, 0)

        await message.answer(greeting)
