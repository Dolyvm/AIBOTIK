"""Модели данных персонажа."""

from dataclasses import dataclass
from typing import List


@dataclass
class CharacterData:
    """Данные персонажа из character card."""

    name: str
    description: str
    personality: str
    scenario: str
    first_message: str
    example_dialogue: str
    system_prompt: str = ""
    post_history: str = ""
    alternate_greetings: List[str] = None  # Альтернативные приветствия (сценарии)

    def __post_init__(self):
        """Инициализация после создания."""
        if self.alternate_greetings is None:
            self.alternate_greetings = []

    def get_greeting(self, index: int = 0) -> str:
        """
        Получает приветствие по индексу.

        Args:
            index: 0 = основное приветствие, 1+ = альтернативные

        Returns:
            Текст приветствия
        """
        if index == 0:
            return self.first_message

        # Альтернативные приветствия (индекс 1 = первое альтернативное)
        alt_index = index - 1
        if 0 <= alt_index < len(self.alternate_greetings):
            return self.alternate_greetings[alt_index]

        # Если индекс неверный, возвращаем основное
        return self.first_message

    def get_total_greetings(self) -> int:
        """Возвращает общее количество приветствий (основное + альтернативные)."""
        return 1 + len(self.alternate_greetings)

    def to_dict(self) -> dict:
        """Преобразует в словарь."""
        return {
            "name": self.name,
            "description": self.description,
            "personality": self.personality,
            "scenario": self.scenario,
            "first_message": self.first_message,
            "example_dialogue": self.example_dialogue,
            "system_prompt": self.system_prompt,
            "post_history": self.post_history,
            "alternate_greetings": self.alternate_greetings,
        }
