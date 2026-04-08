from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import sys
from pathlib import Path
import os

from shared.services.analytics import AnalyticsService

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.database import get_session
from shared.database.repositories import UserRepository
from shared.config import ADMIN_TELEGRAM_IDS

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    async with get_session() as session:
        user_repo = UserRepository(session)
        user, is_created = await user_repo.get_or_create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            do_commit=False
        )
        if is_created:
            await AnalyticsService.track(session, user.telegram_id, "bot_enter")
        await user_repo.commit()

    from shared.subscription_plans import PLAN_LIMITS
    plan_config = PLAN_LIMITS.get(user.subscription_plan, {})
    plan_name = plan_config.get("display_name", "Free")
    await message.answer_sticker("CAACAgIAAxkBAAEQ4yJp1qPgXQaySjVyfn05QfgHGBR5TgACppsAAoTDOUkHvrOFfJvx9TsE")
    await message.answer(
        f"Привет, {message.from_user.first_name} 👋\n\n"
        "Добро пожаловать в AIKAI — место, где оживают любимые персонажи и создаются миры!\n\n"
        f"Твой тариф: {plan_name}\n\n"
        "Выбирай героя или вселенную и начинай свою историю!\n\n"
        "👇 Открой меню ниже"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):

    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return

    webapp_url = os.getenv("WEBAPP_URL", "").split("?")[0].rstrip("/")
    admin_url = f"{webapp_url}/admin/"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Открыть Админ-панель",
                web_app=WebAppInfo(url=admin_url)
            )
        ]
    ])

    await message.answer(
        "Админ-панель\n\n"
        "Нажмите кнопку ниже для открытия панели:",
        reply_markup=keyboard
    )
