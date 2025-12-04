"""Модели сессии пользователя и истории сообщений."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from .state import CharacterState
from config.scenario_states import get_initial_state


@dataclass
class Message:
    """Сообщение в истории диалога."""
    role: str  # 'user' или 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class UserSession:
    """Сессия пользователя с ботом."""

    user_id: int
    user_name: str

    current_character: str = "maya"  
    scenario_index: int = 0  

    # История сообщений
    messages: List[Message] = field(default_factory=list)

    # Состояние персонажа для этого пользователя
    character_state: CharacterState = field(default_factory=CharacterState)

    # Summary (если есть)
    summary: str | None = None
    summary_created_at: int = 0  # Номер сообщения, когда создан summary

    # Метаданные
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    message_count: int = 0

    def add_message(self, role: str, content: str):
        """Добавляет сообщение в историю."""
        self.messages.append(Message(role=role, content=content))
        self.message_count += 1
        self.last_activity = datetime.now()

    def get_recent_messages(self, count: int) -> List[Message]:
        """Возвращает последние N сообщений."""
        return self.messages[-count:]

    def get_messages_for_context(self) -> List[dict]:
        """Возвращает сообщения в формате для API."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.messages
        ]

    def switch_character(self, character_id: str):
        """
        Переключает персонажа и сбрасывает состояние.

        Args:
            character_id: ID персонажа (имя файла без .png)
        """
        self.current_character = character_id
        self.scenario_index = 0  # Сбрасываем на основной сценарий
        # Сбрасываем историю и состояние при смене персонажа
        self.messages = []
        self.character_state = CharacterState()
        self.summary = None
        self.summary_created_at = 0
        self.message_count = 0

    def switch_scenario(self, scenario_index: int):
        """
        Переключает сценарий и сбрасывает историю.

        Args:
            scenario_index: Индекс сценария (0 = основной, 1+ = альтернативные)
        """
        self.scenario_index = scenario_index
        # Сбрасываем историю при смене сценария
        self.messages = []

        # Получаем начальные значения для этого сценария
        initial_state = get_initial_state(self.current_character, scenario_index)
        self.character_state = CharacterState(**initial_state)

        self.summary = None
        self.summary_created_at = 0
        self.message_count = 0
