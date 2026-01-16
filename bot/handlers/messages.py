from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import json
import os
import sys
import httpx
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import get_active_chat, update_chat_full, update_balance, get_user
from shared.card_parser import get_character
from services.llm import LLMClient
from services.imagegen import ImageGenerator
from services.context_manager import ContextManager

router = Router()

# Initialize clients
llm = LLMClient(api_key=os.getenv("OPENROUTER_API_KEY"))
imagegen = ImageGenerator(api_key=os.getenv("MODELSLAB_API_KEY"))
context_manager = ContextManager(llm_client=llm, summary_threshold=15)


def load_world(world_id: str) -> dict:
    world_path = Path("/app/content/worlds") / f"{world_id}.json"
    with open(world_path) as f:
        return json.load(f)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: Message):
    """Заглушка: весь чат теперь только в WebApp"""
    await message.answer(
        "💬 Все диалоги теперь доступны только в WebApp!\n\n"
        "👉 Нажмите кнопку меню внизу или команду /start чтобы открыть WebApp"
    )


# ============== PHOTO COMMANDS ==============

@router.message(Command("photo"))
async def handle_photo(message: Message):
    """
    Generate character photo.
    Usage: 
      /photo - показать меню выбора сценария
      /photo random - случайный сценарий
      /photo <variation_name> - конкретный сценарий
    """
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user.balance < 50:
        await message.answer(f"❌ Нужно 50 токенов. У тебя: {user.balance}")
        return

    chat = await get_active_chat(user_id)
    if not chat or chat.chat_type != "character":
        await message.answer("📸 Генерация фото доступна только для персонажей. Выбери персонажа в меню.")
        return

    # Получить аргумент команды
    args = message.text.split(maxsplit=1)
    variation_name = args[1].strip().lower() if len(args) > 1 else None

    # Получить доступные вариации
    meta = imagegen.character_meta.get(chat.target_id, {})
    variations = meta.get("variations", {})
    
    # Если нет аргумента - показать меню
    if not variation_name:
        if variations:
            keyboard = build_variation_keyboard(chat.target_id, variations)
            await message.answer(
                "📸 Выбери сценарий для фото:\n\n"
                "🎲 **random** - случайный сценарий\n"
                "🚗 **car** - в машине (базовый)\n" +
                "\n".join([f"• **{name}**" for name in variations.keys()]),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            # Нет вариаций - сразу генерируем базовое
            await generate_and_send_photo(message, chat.target_id, None)
        return

    # Random - выбрать случайную вариацию
    if variation_name == "random":
        import random
        if variations:
            variation_name = random.choice(list(variations.keys()))
        else:
            variation_name = None
    
    # Проверить что вариация существует
    elif variation_name not in ["car", "base"] and variation_name not in variations:
        await message.answer(
            f"❌ Сценарий '{variation_name}' не найден.\n\n"
            f"Доступные: random, car, " + ", ".join(variations.keys())
        )
        return
    
    # car/base = базовый промпт без вариации
    if variation_name in ["car", "base"]:
        variation_name = None

    await generate_and_send_photo(message, chat.target_id, variation_name)


def build_variation_keyboard(character_id: str, variations: dict) -> InlineKeyboardMarkup:
    """Создать клавиатуру с вариациями"""
    buttons = [
        [InlineKeyboardButton(text="🎲 Случайный", callback_data=f"photo:{character_id}:random")],
        [InlineKeyboardButton(text="🚗 В машине (базовый)", callback_data=f"photo:{character_id}:base")],
    ]
    
    # Добавить вариации по 2 в ряд
    variation_buttons = []
    for name in variations.keys():
        emoji = get_variation_emoji(name)
        variation_buttons.append(
            InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"photo:{character_id}:{name}")
        )
    
    # Группируем по 2
    for i in range(0, len(variation_buttons), 2):
        buttons.append(variation_buttons[i:i+2])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_variation_emoji(name: str) -> str:
    """Эмодзи для вариации"""
    emojis = {
        "car": "🚗",
        "street": "🌃",
        "bedroom": "🛏️",
        "mirror": "🪞",
        "pool": "🏊",
        "shower": "🚿",
        "beach": "🏖️",
        "lingerie": "👙",
        "bikini": "👙",
    }
    for key, emoji in emojis.items():
        if key in name.lower():
            return emoji
    return "📸"


@router.callback_query(F.data.startswith("photo:"))
async def handle_photo_callback(callback: CallbackQuery):
    """Обработка нажатия кнопки выбора вариации"""
    await callback.answer()
    
    # Парсим callback_data: photo:character_id:variation_name
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    
    _, character_id, variation_name = parts
    
    user = await get_user(callback.from_user.id)
    if user.balance < 50:
        await callback.message.answer(f"❌ Нужно 50 токенов. У тебя: {user.balance}")
        return
    
    # Random
    if variation_name == "random":
        import random
        meta = imagegen.character_meta.get(character_id, {})
        variations = list(meta.get("variations", {}).keys())
        variation_name = random.choice(variations) if variations else None
    elif variation_name == "base":
        variation_name = None
    
    await generate_and_send_photo(callback.message, character_id, variation_name, callback.from_user.id)


async def generate_and_send_photo(message: Message, character_id: str, variation_name: str = None, user_id: int = None):
    """Генерация и отправка фото"""
    user_id = user_id or message.from_user.id
    
    scenario_text = f"сценарий: **{variation_name}**" if variation_name else "базовый сценарий"
    status_msg = await message.answer(f"🎨 Генерирую фото ({scenario_text})...\n⏳ Это может занять до 60 секунд")

    try:
        # Генерация
        if variation_name:
            image_url = await imagegen.generate_variation(character_id, variation_name)
        else:
            image_url = await imagegen.generate(character_id)
        
        # Списываем токены
        await update_balance(user_id, -50)

        # Скачиваем и отправляем
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(3):
                response = await client.get(image_url)
                if response.status_code == 200:
                    image_data = response.content
                    photo = BufferedInputFile(image_data, filename="photo.jpg")
                    
                    await status_msg.delete()
                    await message.answer_photo(
                        photo, 
                        caption=f"📸 {scenario_text}\n💰 -50 токенов" if variation_name else "📸 Фото готово!\n💰 -50 токенов"
                    )
                    return
                elif response.status_code != 404:
                    response.raise_for_status()
                await asyncio.sleep(3)
        
        raise httpx.HTTPError(f"Failed to download after 3 attempts")

    except TimeoutError:
        await status_msg.edit_text("❌ Таймаут: сервер перегружен. Попробуй позже.")
    except ValueError as e:
        await status_msg.edit_text(f"❌ Ошибка API: {e}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")


# ============== VARIATIONS LIST ==============

@router.message(Command("variations"))
async def handle_variations(message: Message):
    """Показать список доступных вариаций для текущего персонажа"""
    chat = await get_active_chat(message.from_user.id)
    if not chat or chat.chat_type != "character":
        await message.answer("Сначала выбери персонажа в меню 🎭")
        return
    
    meta = imagegen.character_meta.get(chat.target_id, {})
    variations = meta.get("variations", {})
    
    if not variations:
        await message.answer("У этого персонажа нет дополнительных сценариев для фото.")
        return
    
    text = "📸 **Доступные сценарии для фото:**\n\n"
    text += "• `/photo` - базовый (в машине)\n"
    text += "• `/photo random` - случайный\n\n"
    
    for name in variations.keys():
        emoji = get_variation_emoji(name)
        text += f"• `/photo {name}` {emoji}\n"
    
    text += "\n💰 Стоимость: 50 токенов"
    
    await message.answer(text, parse_mode="Markdown")