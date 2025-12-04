"""FastAPI сервер для Telegram WebApp."""

import logging
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config.greeting_translations import get_translated_greeting

logger = logging.getLogger(__name__)


def create_app(storage, character_manager) -> FastAPI:
    """
    Создает FastAPI приложение для WebApp.

    Args:
        storage: InMemoryStorage для доступа к сессиям
        character_manager: CharacterManager для доступа к персонажам

    Returns:
        Настроенное FastAPI приложение
    """
    app = FastAPI(title="AI Botik WebApp")

    # CORS для Telegram WebApp
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://web.telegram.org"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Монтируем статические файлы
    static_path = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Монтируем папку с персонажами для отображения картинок
    characters_path = Path(__file__).parent.parent / "characters"
    app.mount("/characters", StaticFiles(directory=str(characters_path)), name="characters")

    @app.get("/")
    async def root():
        """Главная страница WebApp."""
        return FileResponse(static_path / "index.html")

    @app.get("/api/characters")
    async def get_characters() -> JSONResponse:
        """
        Возвращает список всех персонажей.

        Returns:
            JSON с массивом персонажей: [{id, name, total_greetings}, ...]
        """
        characters = []
        for char_id, char_data in character_manager.get_all_characters().items():
            characters.append({
                "id": char_id,
                "name": char_data.name,
                "total_greetings": char_data.get_total_greetings(),
                "image": f"/characters/{char_id}.png"
            })
        return JSONResponse(content={"characters": characters})

    @app.get("/api/characters/{character_id}/scenarios")
    async def get_scenarios(character_id: str) -> JSONResponse:
        """
        Возвращает список сценариев для персонажа.

        Args:
            character_id: ID персонажа

        Returns:
            JSON с массивом сценариев
        """
        character = character_manager.get_character(character_id)
        if not character:
            return JSONResponse(
                status_code=404,
                content={"error": "Character not found"}
            )

        scenarios = []

        # Основной сценарий
        main_greeting = get_translated_greeting(character_id, 0, character)
        main_preview = main_greeting[:100].replace('\n', ' ')
        scenarios.append({
            "index": 0,
            "name": "Основной",
            "preview": main_preview + "..."
        })

        # Альтернативные сценарии
        for i in range(1, character.get_total_greetings()):
            alt_greeting = get_translated_greeting(character_id, i, character)
            preview = alt_greeting[:100].replace('\n', ' ')
            scenarios.append({
                "index": i,
                "name": f"Альтернативный {i}",
                "preview": preview + "..."
            })

        return JSONResponse(content={"scenarios": scenarios})

    @app.get("/api/characters/{character_id}/scenarios/{scenario_index}/full")
    async def get_full_scenario(character_id: str, scenario_index: int) -> JSONResponse:
        """
        Возвращает полный текст приветствия для сценария.

        Args:
            character_id: ID персонажа
            scenario_index: Индекс сценария

        Returns:
            JSON с полным текстом приветствия
        """
        character = character_manager.get_character(character_id)
        if not character:
            return JSONResponse(
                status_code=404,
                content={"error": "Character not found"}
            )

        # Получаем полный текст приветствия
        full_text = get_translated_greeting(character_id, scenario_index, character)

        return JSONResponse(content={"text": full_text})

    @app.get("/api/status/{user_id}")
    async def get_status(user_id: int) -> JSONResponse:
        """
        Возвращает статус сессии пользователя.

        Args:
            user_id: ID пользователя в Telegram

        Returns:
            JSON со статусом сессии
        """
        logger.info(f"=== API /api/status/{user_id} called ===")
        logger.info(f"Requested user_id: {user_id}, type: {type(user_id)}")

        try:
            session = await storage.get_session(user_id, "User")
            logger.info(f"Session retrieved: current_character={session.current_character}, scenario={session.scenario_index}")

            state = session.character_state
            logger.info(f"Character state: trust={state.trust}, affection={state.affection}")

            character = character_manager.get_character(session.current_character)
            character_name = character.name if character else "Unknown"
            logger.info(f"Character found: {character_name}")

            response_data = {
                "character_id": session.current_character,
                "character_name": character_name,
                "scenario_index": session.scenario_index,
                "state": {
                    "trust": state.trust,
                    "affection": state.affection,
                    "arousal": state.arousal,
                    "comfort": state.comfort,
                    "relationship_stage": state.relationship_stage.value,
                    "mood": state.mood.value
                },
                "message_count": session.message_count
            }
            logger.info(f"Returning status response: {response_data}")
            return JSONResponse(content=response_data)
        except Exception as e:
            logger.error(f"Error in get_status: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )

    return app


async def run_server(app: FastAPI, host: str = "0.0.0.0", port: int = 8080):
    """
    Запускает FastAPI сервер.

    Args:
        app: FastAPI приложение
        host: Хост для прослушивания
        port: Порт для прослушивания
    """
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting WebApp server on {host}:{port}")
    await server.serve()
