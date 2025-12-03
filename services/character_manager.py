"""Менеджер для управления персонажами."""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from models.character import CharacterData
from services.card_parser import CharacterCardParser

logger = logging.getLogger(__name__)


class CharacterManager:
    """Управление персонажами (загрузка, хранение, получение)."""

    def __init__(self, characters_dir: Path):
        """
        Args:
            characters_dir: Путь к директории с PNG character cards
        """
        self.characters_dir = characters_dir
        self.characters: Dict[str, CharacterData] = {}
        self._load_all_characters()

    def _load_all_characters(self):
        """Загружает все PNG character cards из директории."""
        if not self.characters_dir.exists():
            logger.error(f"Characters directory not found: {self.characters_dir}")
            return

        png_files = list(self.characters_dir.glob("*.png"))
        logger.info(f"Found {len(png_files)} PNG files in characters directory")

        for png_file in png_files:
            try:
                character_data = CharacterCardParser.extract_from_png(png_file)
                character_id = png_file.stem  # Имя файла без расширения
                self.characters[character_id] = character_data
                logger.info(f"Loaded character: {character_data.name} (ID: {character_id})")
            except Exception as e:
                logger.error(f"Failed to load character from {png_file.name}: {e}")

        if not self.characters:
            logger.warning("No characters loaded!")

    def get_character(self, character_id: str) -> Optional[CharacterData]:
        """
        Получает данные персонажа по ID.

        Args:
            character_id: ID персонажа (имя файла без .png)

        Returns:
            CharacterData или None, если персонаж не найден
        """
        return self.characters.get(character_id)

    def get_all_characters(self) -> Dict[str, CharacterData]:
        """Возвращает словарь всех загруженных персонажей."""
        return self.characters

    def get_character_list(self) -> List[tuple[str, str]]:
        """
        Возвращает список персонажей для отображения.

        Returns:
            Список кортежей (character_id, character_name)
        """
        return [(cid, char.name) for cid, char in self.characters.items()]

    def character_exists(self, character_id: str) -> bool:
        """Проверяет, существует ли персонаж с данным ID."""
        return character_id in self.characters

    def get_default_character_id(self) -> str:
        """Возвращает ID персонажа по умолчанию."""
        if "maya" in self.characters:
            return "maya"
        return next(iter(self.characters.keys())) if self.characters else "maya"
