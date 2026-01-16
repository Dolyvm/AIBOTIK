from aiogram import Router, F
from aiogram.types import Message
import json
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.repository import create_or_reset_chat, update_chat_history
from shared.card_parser import get_character

router = Router()


def load_world(world_id: str) -> dict:
    """Load world from JSON file"""
    world_path = Path("/app/content/worlds") / f"{world_id}.json"
    with open(world_path) as f:
        return json.load(f)


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    """Handle data from WebApp"""
    data = json.loads(message.web_app_data.data)
    user_id = message.from_user.id

    # {action: "start_chat", type: "character", id: "alexis", scenario: 0}
    if data.get("action") == "start_chat":
        chat = await create_or_reset_chat(
            user_id=user_id,
            chat_type=data["type"],
            target_id=data["id"],
            scenario_index=data.get("scenario", 0)
        )

        # Get greeting
        if data["type"] == "character":
            character = get_character(Path("/app/content/characters"), data["id"])
            if not character:
                await message.answer("❌ Персонаж не найден")
                return

            if data.get("scenario", 0) == 0:
                greeting = character["first_mes"]
            else:
                alt_index = data["scenario"] - 1
                if alt_index < len(character.get("alternate_greetings", [])):
                    greeting = character["alternate_greetings"][alt_index]
                else:
                    greeting = character["first_mes"]
        else:
            world = load_world(data["id"])
            greeting = world["intro_message"]

        # Replace placeholders
        greeting = greeting.replace("{{user}}", message.from_user.first_name)
        greeting = greeting.replace("{{char}}", character.get("name", "") if data["type"] == "character" else "")

        # Save greeting to history
        history = [{"role": "assistant", "content": greeting}]
        await update_chat_history(chat.id, history, 0)

        await message.answer(greeting)
