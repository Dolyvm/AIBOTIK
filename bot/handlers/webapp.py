from aiogram import Router, F
from aiogram.types import Message
import json
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.database import get_session
from shared.database.repositories import ChatRepository, MessageRepository
from shared.services.content_loader import get_first_message

router = Router()


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    data = json.loads(message.web_app_data.data)
    user_id = message.from_user.id

    if data.get("action") == "start_chat":
        async with get_session() as session:
            chat_repo = ChatRepository(session)
            message_repo = MessageRepository(session)

            chat = await chat_repo.create_chat(
                user_id=user_id,
                chat_type=data["type"],
                target_id=data["id"],
                scenario_index=data.get("scenario", 0)
            )

            greeting = await get_first_message(
                chat_type=data["type"],
                target_id=data["id"],
                scenario_index=data.get("scenario", 0),
                user_name=message.from_user.first_name,
            )

            if not greeting:
                await message.answer("Контент не найден")
                return

            await message_repo.add(
                chat_id=chat.id,
                role="assistant",
                content=greeting,
                tokens_used=0
            )

        await message.answer(greeting)
