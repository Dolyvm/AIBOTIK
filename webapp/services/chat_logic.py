import os
import json
import httpx
from pathlib import Path
import sys

# Добавляем путь к корню, чтобы видеть bot/ и shared/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import Chat
from shared.card_parser import get_character
from shared.repository import get_user
# ИМПОРТИРУЕМ НАШИ МОЩНЫЕ ПРОМПТЫ ИЗ БОТА
from bot.services.prompt_builder import build_character_prompt, build_world_prompt

# Конфигурация
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "mistralai/mistral-small-creative" 


async def generate_response(chat: Chat, user_input: str) -> tuple[str, list]:
    """Генерация ответа для WebApp"""

    # 1. Загрузка данных
    history = json.loads(chat.history)
    state = json.loads(chat.state)

    # Получаем имя пользователя из БД
    user = await get_user(chat.user_id)
    user_name = user.username if user and user.username else "Путешественник"

    # 2. Формируем System Prompt
    if chat.chat_type == "character":
        # Загружаем персонажа
        character = get_character(Path("/app/content/characters"), chat.target_id)
        if not character:
            return "Ошибка: Персонаж не найден", history

        system_prompt = build_character_prompt(
            character=character,
            state=state,
            summary=chat.summary, # Используем summary из БД
            user_name=user_name
        )

        # Для персонажей добавляем инструкцию писать короче
        system_prompt += "\n\nФОРМАТ ОТВЕТА: Пиши КРАТКО и ДИНАМИЧНО. 2-3 абзаца максимум. Меньше внутренних размышлений, больше действий и диалога. Избегай длинных описаний чувств."

        # Параметры для персонажей - короткие ответы
        max_tokens = 200

    else:
        # Загружаем мир
        world_path = Path("/app/content/worlds") / f"{chat.target_id}.json"
        if not world_path.exists():
             return "Ошибка: Мир не найден", history

        with open(world_path) as f:
            world = json.load(f)

        # ИСПОЛЬЗУЕМ ПРАВИЛЬНЫЙ ГЕНЕРАТОР ПРОМПТА ДЛЯ МИРА
        system_prompt = build_world_prompt(
            world=world,
            summary=chat.summary,
            user_name=user_name
        )

        # Параметры для миров - более длинные описания
        max_tokens = 400

    # 3. Формируем историю сообщений
    # System prompt всегда первый
    messages = [{"role": "system", "content": system_prompt}]
    
    # Добавляем последние сообщения (чтобы не перегружать контекст)
    # Берем последние 10, но фильтруем, чтобы не дублировать системные
    messages.extend(history[-10:])
    
    # Добавляем текущее сообщение пользователя
    messages.append({"role": "user", "content": user_input})

    # 4. Запрос к LLM
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": MODEL,
                    "messages": messages,
                    "temperature": 0.8, # Чуть выше креативность для RP
                    "max_tokens": max_tokens,  # Используем переменную: 200 для персонажей, 400 для миров
                    # Repetition penalty помогает избегать зацикливания фраз
                    "repetition_penalty": 1.1
                },
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://your-site.com", # Требование OpenRouter
                }
            )
            response.raise_for_status()
            data = response.json()
            
            if "choices" not in data or len(data["choices"]) == 0:
                return "Ошибка API: Пустой ответ", history
                
            ai_text = data["choices"][0]["message"]["content"]
            
            # Чистим <meta> теги, так как в WebApp мы их пока не обрабатываем визуально,
            # но промпт их генерирует. Можно просто вырезать их для чистоты текста.
            import re
            ai_text = re.sub(r'<meta>.*?</meta>', '', ai_text, flags=re.DOTALL).strip()

    except Exception as e:
        print(f"LLM Error: {e}")
        return "⚠️ Произошла ошибка при генерации ответа. Попробуйте еще раз.", history

    # 5. Обновляем историю
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": ai_text})

    return ai_text, history