"""Обработчики команд бота."""

import html
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

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
/character — выбрать персонажа
/scenario — выбрать сценарий
/status — показать состояние отношений
/reset — начать диалог заново
/help — помощь"""

    await message.answer(welcome_text)
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
        greeting = current_char.get_greeting(scenario_idx)
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


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    help_text = """<b>Как пользоваться ботом:</b>

Просто пиши сообщения персонажу, и он будет отвечать.

<b>Команды:</b>
/start — начать работу с ботом
/character — выбрать персонажа
/scenario — выбрать альтернативный сценарий
/status — показать статистику отношений
/reset — начать диалог заново
/help — показать это сообщение

<b>Особенности:</b>
• Персонаж запоминает ваш диалог и развивается вместе с вами
• Отношения меняются в зависимости от ваших действий
• Бот автоматически создаёт summary для длинных диалогов
• Можно переключаться между разными персонажами
• Альтернативные сценарии — разные стартовые ситуации для персонажа

<b>Совет:</b> Будьте естественны, персонаж реагирует на ваши слова и действия."""

    await message.answer(help_text)
    logger.info(f"User {message.from_user.id} requested help")


@router.message(Command("character"))
async def cmd_character(message: Message, storage, character_manager):
    """Обработчик команды /character - выбор персонажа."""
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"

    # Парсим аргументы команды
    args = message.text.split(maxsplit=1)

    # Если нет аргументов - показываем список персонажей
    if len(args) == 1:
        char_list = character_manager.get_character_list()

        if not char_list:
            await message.answer("Нет доступных персонажей!")
            return

        session = await storage.get_session(user_id, user_name)
        current_id = session.current_character

        char_text = "<b>Доступные персонажи:</b>\n\n"
        for char_id, char_name in char_list:
            marker = "✅" if char_id == current_id else "○"
            char_text += f"{marker} <code>{html.escape(char_id)}</code> — {html.escape(char_name)}\n"

        char_text += "\n<b>Использование:</b>\n"
        char_text += "<code>/character &lt;id&gt;</code> — выбрать персонажа\n\n"
        char_text += "Например: <code>/character alexis</code>"

        await message.answer(char_text)
        return

    # Если есть аргумент - переключаем персонажа
    new_character_id = args[1].strip().lower()

    if not character_manager.character_exists(new_character_id):
        await message.answer(
            f"Персонаж <code>{html.escape(new_character_id)}</code> не найден!\n\n"
            "Используй <code>/character</code> чтобы увидеть список доступных персонажей."
        )
        return

    # Получаем сессию и переключаем персонажа
    session = await storage.get_session(user_id, user_name)

    if session.current_character == new_character_id:
        new_char = character_manager.get_character(new_character_id)
        await message.answer(f"Ты уже общаешься с {html.escape(new_char.name)}!")
        return

    # Переключаем персонажа
    session.switch_character(new_character_id)
    new_char = character_manager.get_character(new_character_id)

    await message.answer(
        f"Персонаж изменён на <b>{html.escape(new_char.name)}</b>!\n\n"
        "История и отношения сброшены. Начни новый диалог!"
    )
    logger.info(f"User {user_id} switched to character: {new_character_id}")


@router.message(Command("scenario"))
async def cmd_scenario(message: Message, storage, character_manager):
    """Обработчик команды /scenario - выбор сценария (альтернативного приветствия)."""
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"

    session = await storage.get_session(user_id, user_name)
    character = character_manager.get_character(session.current_character)

    if not character:
        await message.answer("Персонаж не найден!")
        return

    # Парсим аргументы команды
    args = message.text.split(maxsplit=1)

    # Если нет аргументов - показываем список сценариев
    if len(args) == 1:
        total = character.get_total_greetings()

        if total == 1:
            await message.answer(
                f"У персонажа <b>{html.escape(character.name)}</b> нет альтернативных сценариев.\n\n"
                "Доступен только основной сценарий."
            )
            return

        scenario_text = f"<b>Сценарии для {html.escape(character.name)}:</b>\n\n"

        # Основной сценарий
        main_preview = character.first_message[:80].replace('\n', ' ')
        marker = "✅" if session.scenario_index == 0 else "○"
        scenario_text += f"{marker} <code>0</code> — Основной\n"
        scenario_text += f"   <i>{html.escape(main_preview)}...</i>\n\n"

        # Альтернативные сценарии
        for i, alt_greeting in enumerate(character.alternate_greetings, 1):
            preview = alt_greeting[:80].replace('\n', ' ')
            marker = "✅" if session.scenario_index == i else "○"
            scenario_text += f"{marker} <code>{i}</code> — Альтернативный {i}\n"
            scenario_text += f"   <i>{html.escape(preview)}...</i>\n\n"

        scenario_text += "<b>Использование:</b>\n"
        scenario_text += "<code>/scenario &lt;номер&gt;</code> — выбрать сценарий\n\n"
        scenario_text += "Например: <code>/scenario 1</code>\n\n"
        scenario_text += "⚠️ Смена сценария сбросит историю диалога!"

        await message.answer(scenario_text)
        return

    # Если есть аргумент - переключаем сценарий
    try:
        scenario_num = int(args[1].strip())
    except ValueError:
        await message.answer(
            "Неверный номер сценария!\n\n"
            "Используй <code>/scenario</code> чтобы увидеть список доступных сценариев."
        )
        return

    total = character.get_total_greetings()

    if scenario_num < 0 or scenario_num >= total:
        await message.answer(
            f"Сценарий <code>{scenario_num}</code> не существует!\n\n"
            f"Доступны сценарии от 0 до {total - 1}.\n\n"
            "Используй <code>/scenario</code> чтобы увидеть список."
        )
        return

    if session.scenario_index == scenario_num:
        await message.answer(f"Этот сценарий уже выбран!")
        return

    # Переключаем сценарий
    session.switch_scenario(scenario_num)

    scenario_name = "Основной" if scenario_num == 0 else f"Альтернативный {scenario_num}"

    # Отправляем приветствие из нового сценария
    greeting = character.get_greeting(scenario_num)

    await message.answer(
        f"Сценарий изменён на: <b>{scenario_name}</b>\n\n"
        "История и отношения сброшены!"
    )

    # Добавляем приветствие персонажа в историю
    from utils.helpers import format_response
    session.add_message("assistant", greeting)
    formatted_greeting = format_response(greeting)
    await message.answer(formatted_greeting, parse_mode="HTML")

    logger.info(f"User {user_id} switched to scenario {scenario_num} for character {session.current_character}")
