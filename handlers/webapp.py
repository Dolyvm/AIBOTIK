"""Обработчик данных от Telegram WebApp."""

import html
import json
import logging
from aiogram import Router, F
from aiogram.types import Message

from config.greeting_translations import get_translated_greeting
from utils.helpers import format_response

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message, storage, character_manager):
    """
    Обработчик данных от WebApp.

    Получает выбранного персонажа и сценарий, переключает сессию
    и отправляет приветствие.
    """
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"

    try:
        # Парсим данные от WebApp
        data = json.loads(message.web_app_data.data)
        character_id = data.get('character_id')
        scenario_index = data.get('scenario_index', 0)

        logger.info(f"WebApp data from user {user_id}: character={character_id}, scenario={scenario_index}")

        # Проверяем, что персонаж существует
        if not character_manager.character_exists(character_id):
            await message.answer(
                f"Ошибка: персонаж <code>{html.escape(character_id)}</code> не найден!"
            )
            return

        # Получаем сессию
        session = await storage.get_session(user_id, user_name)

        # Проверяем, нужно ли переключать персонажа
        if session.current_character != character_id:
            session.switch_character(character_id)
            logger.info(f"User {user_id} switched to character: {character_id}")

        # Переключаем сценарий
        session.switch_scenario(scenario_index)
        logger.info(f"User {user_id} switched to scenario {scenario_index}")

        # Получаем персонажа и приветствие
        character = character_manager.get_character(character_id)
        greeting = get_translated_greeting(character_id, scenario_index, character)

        # Добавляем приветствие в историю
        session.add_message("assistant", greeting)

        # Формируем название сценария
        scenario_name = "Основной" if scenario_index == 0 else f"Альтернативный {scenario_index}"

        # Отправляем подтверждение
        await message.answer(
            f"✅ Выбран персонаж: <b>{html.escape(character.name)}</b>\n"
            f"📖 Сценарий: <b>{scenario_name}</b>\n\n"
            "История и отношения обновлены!"
        )

        # Отправляем приветствие персонажа
        formatted_greeting = format_response(greeting)
        await message.answer(formatted_greeting, parse_mode="HTML")

        logger.info(f"User {user_id} started dialog with {character_id}, scenario {scenario_index}")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse WebApp data: {e}")
        await message.answer("Ошибка обработки данных от WebApp!")
    except Exception as e:
        logger.error(f"Error handling WebApp data: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке выбора!")
