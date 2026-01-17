from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import get_or_create_user

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )

    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        f"Твой баланс: {user.balance} токенов\n\n"
        "Нажми кнопку меню внизу, чтобы выбрать персонажа или вселенную."
    )
