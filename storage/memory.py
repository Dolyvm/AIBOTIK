"""In-memory хранилище сессий пользователей."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from models.session import UserSession

logger = logging.getLogger(__name__)


class InMemoryStorage:
    """Хранилище сессий пользователей в памяти (для прототипа)."""

    def __init__(self):
        self._sessions: Dict[int, UserSession] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, user_id: int, user_name: str = "User") -> UserSession:
        """
        Получает или создаёт сессию пользователя.

        Args:
            user_id: ID пользователя Telegram
            user_name: Имя пользователя

        Returns:
            UserSession для данного пользователя
        """
        async with self._lock:
            if user_id not in self._sessions:
                logger.info(f"Creating new session for user {user_id} ({user_name})")
                self._sessions[user_id] = UserSession(
                    user_id=user_id,
                    user_name=user_name
                )
            return self._sessions[user_id]

    async def reset_session(self, user_id: int, user_name: str = "User") -> UserSession:
        """
        Сбрасывает сессию пользователя (создаёт новую), сохраняя выбранного персонажа.

        Args:
            user_id: ID пользователя
            user_name: Имя пользователя

        Returns:
            Новая UserSession
        """
        async with self._lock:
            # Сохраняем текущего персонажа, если сессия существует
            current_character = "maya"  # Default
            if user_id in self._sessions:
                current_character = self._sessions[user_id].current_character

            logger.info(f"Resetting session for user {user_id}, keeping character: {current_character}")
            self._sessions[user_id] = UserSession(
                user_id=user_id,
                user_name=user_name,
                current_character=current_character
            )
            return self._sessions[user_id]

    async def delete_session(self, user_id: int):
        """
        Удаляет сессию пользователя.

        Args:
            user_id: ID пользователя
        """
        async with self._lock:
            if user_id in self._sessions:
                logger.info(f"Deleting session for user {user_id}")
                del self._sessions[user_id]

    def get_active_sessions_count(self) -> int:
        """Возвращает количество активных сессий."""
        return len(self._sessions)

    async def cleanup_inactive(self, max_age_hours: int = 24):
        """
        Удаляет неактивные сессии.

        Args:
            max_age_hours: Максимальный возраст сессии в часах
        """
        async with self._lock:
            now = datetime.now()
            to_delete = []
            for user_id, session in self._sessions.items():
                age = (now - session.last_activity).total_seconds() / 3600
                if age > max_age_hours:
                    to_delete.append(user_id)

            for user_id in to_delete:
                logger.info(f"Cleaning up inactive session for user {user_id}")
                del self._sessions[user_id]

            if to_delete:
                logger.info(f"Cleaned up {len(to_delete)} inactive sessions")
