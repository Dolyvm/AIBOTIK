"""Обработчики команд бота."""

import html
import logging
import os
from dotenv import load_dotenv
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

from config.greeting_translations import get_translated_greeting

# Загружаем переменные окружения из .env
load_dotenv()

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, storage, character_manager):
    """Обработчик команды /start."""
    user_name = message.from_user.first_name or "незнакомец"
    user_id = message.from_user.id

    # Получаем сессию и текущего персонажа
    session = await storage.get_session(user_id, user_name)
    current_char = character_manager.get_character(session.current_character)
    char_name = current_char.name if current_char else "персонаж"

    welcome_text = f"""Привет, {html.escape(user_name)}!

Сейчас активен персонаж: <b>{html.escape(char_name)}</b>

Просто напиши что-нибудь, и мы начнём.

<b>Команды:</b>
/status — показать состояние отношений
/reset — начать диалог заново

Используй кнопку <b>🎭 Меню</b> внизу для выбора персонажа и сценария."""

    # Получаем URL WebApp из переменной окружения
    webapp_url = os.getenv("WEBAPP_URL", "http://localhost:8080")

    # Добавляем user_id как URL параметр для fallback
    webapp_url_with_params = f"{webapp_url}?user_id={user_id}"

    # Создаём клавиатуру с кнопкой WebApp
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎭 Меню", web_app=WebAppInfo(url=webapp_url_with_params))]
        ],
        resize_keyboard=True
    )

    await message.answer(welcome_text, reply_markup=keyboard)
    logger.info(f"User {message.from_user.id} started the bot")


@router.message(Command("reset"))
async def cmd_reset(message: Message, storage, character_manager):
    """Обработчик команды /reset."""
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"

    # Получаем текущего персонажа и сценарий до сброса
    old_session = await storage.get_session(user_id, user_name)
    current_char = character_manager.get_character(old_session.current_character)
    char_name = current_char.name if current_char else "персонаж"
    scenario_idx = old_session.scenario_index

    await storage.reset_session(user_id, user_name)

    # Получаем новую сессию после сброса
    new_session = await storage.get_session(user_id, user_name)
    new_session.scenario_index = scenario_idx  # Сохраняем выбранный сценарий

    # Отправляем приветствие с текущего сценария
    if current_char:
        greeting = get_translated_greeting(old_session.current_character, scenario_idx, current_char)
        new_session.add_message("assistant", greeting)

        scenario_name = "Основной" if scenario_idx == 0 else f"Альтернативный {scenario_idx}"

        await message.answer(
            f"Диалог с <b>{html.escape(char_name)}</b> сброшен!\n\n"
            f"Сценарий: <b>{scenario_name}</b>\n"
            "История и отношения очищены."
        )

        # Отправляем приветствие персонажа
        from utils.helpers import format_response
        formatted_greeting = format_response(greeting)
        await message.answer(formatted_greeting, parse_mode="HTML")

        logger.info(f"User {user_id} reset their session, character: {old_session.current_character}, scenario: {scenario_idx}")
    else:
        await message.answer(
            "Диалог сброшен!\n\n"
            "История и отношения очищены."
        )
        logger.info(f"User {user_id} reset their session")


@router.message(Command("status"))
async def cmd_status(message: Message, storage, character_manager):
    """Обработчик команды /status."""
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"

    session = await storage.get_session(user_id, user_name)
    state = session.character_state

    # Получаем имя текущего персонажа
    current_char = character_manager.get_character(session.current_character)
    char_name = current_char.name if current_char else "персонаж"

    status_text = f"""<b>Статистика отношений с {html.escape(char_name)}:</b>

📊 Доверие: {state.trust}/100
💕 Привязанность: {state.affection}/100
🔥 Возбуждение: {state.arousal}/100
😌 Комфорт: {state.comfort}/100

📈 Стадия отношений: {html.escape(state.relationship_stage.value)}
😊 Текущее настроение: {html.escape(state.mood.value)}

💬 Всего сообщений: {session.message_count}
"""

    if state.memorable_events:
        events = "\n".join(f"• {html.escape(event)}" for event in state.memorable_events[-5:])
        status_text += f"\n<b>Важные события:</b>\n{events}"

    await message.answer(status_text)
    logger.info(f"User {user_id} checked status")
