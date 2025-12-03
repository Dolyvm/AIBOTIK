"""Парсер PNG Character Card (TavernCard V2 format)."""

import base64
import json
from pathlib import Path

from PIL import Image

from models.character import CharacterData


class CharacterCardParser:
    """Парсер для извлечения данных персонажа из PNG character card."""

    @staticmethod
    def extract_from_png(png_path: str | Path) -> CharacterData:
        """
        Извлекает данные персонажа из PNG character card.

        Args:
            png_path: Путь к PNG файлу с character card

        Returns:
            CharacterData с данными персонажа

        Raises:
            ValueError: Если в PNG нет данных персонажа
        """
        img = Image.open(png_path)
        img.load()

        # Проверяем tEXt chunks
        if 'chara' in img.info:
            # V2 format - base64 encoded JSON
            raw_data = img.info['chara']
            decoded = base64.b64decode(raw_data)
            card_data = json.loads(decoded.decode('utf-8'))
        elif 'ccv3' in img.info:
            # V3 format
            raw_data = img.info['ccv3']
            decoded = base64.b64decode(raw_data)
            card_data = json.loads(decoded.decode('utf-8'))
        else:
            raise ValueError("No character data found in PNG")

        return CharacterCardParser._parse_card_data(card_data)

    @staticmethod
    def _parse_card_data(card: dict) -> CharacterData:
        """Преобразует card data в CharacterData."""
        # V2 имеет nested 'data'
        data = card.get('data', card)

        return CharacterData(
            name=data.get('name', 'Character'),
            description=data.get('description', ''),
            personality=data.get('personality', ''),
            scenario=data.get('scenario', ''),
            first_message=data.get('first_mes', ''),
            example_dialogue=data.get('mes_example', ''),
            system_prompt=data.get('system_prompt', ''),
            post_history=data.get('post_history_instructions', ''),
            alternate_greetings=data.get('alternate_greetings', [])
        )
