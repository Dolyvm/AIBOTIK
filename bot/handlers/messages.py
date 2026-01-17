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

from shared.services.llm import LLMClient
from shared.services.context_manager import ContextManager

router = Router()

llm = LLMClient(api_key=os.getenv("OPENROUTER_API_KEY"))
context_manager = ContextManager(llm_client=llm, summary_threshold=15)


def load_world(world_id: str) -> dict:
    world_path = Path("/app/content/worlds") / f"{world_id}.json"
    with open(world_path) as f:
        return json.load(f)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: Message):
    await message.answer(
        "💬 Все диалоги теперь доступны только в WebApp!\n\n"
    )