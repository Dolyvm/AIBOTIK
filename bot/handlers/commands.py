from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import sys
from pathlib import Path
import os

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import get_or_create_user
from shared.config import ADMIN_TELEGRAM_IDS

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


@router.message(Command("admin"))
async def cmd_admin(message: Message):

    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return

    webapp_url = os.getenv("WEBAPP_URL")
    admin_url = f"{webapp_url}/admin/"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔧 Открыть Админ-панель",
                web_app=WebAppInfo(url=admin_url)
            )
        ]
    ])

    await message.answer(
        "Админ-панель\n\n"
        "Нажмите кнопку ниже для открытия панели:",
        reply_markup=keyboard
    )
