"""Конфигурация приложения."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из .env файла."""

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str
    WEBAPP_URL: str = "http://localhost:8080"

    # OpenRouter API
    OPENROUTER_API_KEY: str

    # LLM Configuration
    LLM_MODEL: str 

    # Generation Parameters
    TEMPERATURE: float = 0.80
    TOP_P: float = 0.9
    MAX_TOKENS: int = 180
    REPETITION_PENALTY: float = 1.15

    # Summarization Settings
    SUMMARY_TRIGGER_EVERY: int = 20
    SUMMARY_KEEP_RECENT: int = 15

    # Session Settings
    SESSION_CLEANUP_HOURS: int = 24

    # Character Card Path
    CHARACTER_CARD_PATH: Path = Path(__file__).parent.parent / "characters" / "maya.png"

    class Config:
        """Настройки pydantic."""
        env_file = ".env"
        env_file_encoding = "utf-8"
