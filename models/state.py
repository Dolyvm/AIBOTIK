"""Модели состояния персонажа и прогрессии отношений."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Mood(Enum):
    """Текущее настроение персонажа."""
    PROFESSIONAL = "профессиональное"
    NEUTRAL = "нейтральное"
    WARM = "тёплое"
    PLAYFUL = "игривое"
    INTIMATE = "интимное"
    ANNOYED = "раздражённое"
    VULNERABLE = "уязвимое"


class RelationshipStage(Enum):
    """Стадия отношений с пользователем."""
    STRANGER = "незнакомец"          # 0-20
    ACQUAINTANCE = "знакомый"        # 21-40
    COLLEAGUE = "коллега"            # 41-60
    FRIEND = "друг"                  # 61-80
    CLOSE_FRIEND = "близкий друг"    # 81-90
    INTIMATE = "интимные отношения"  # 91-100


@dataclass
class CharacterState:
    """Динамическое состояние персонажа в рамках сессии с пользователем."""

    # Основные метрики (0-100)
    trust: int = 25          # Доверие
    affection: int = 10      # Привязанность
    arousal: int = 0         # Уровень возбуждения
    comfort: int = 30        # Комфорт в присутствии пользователя

    # Текущее состояние
    mood: Mood = Mood.PROFESSIONAL

    # Флаги важных событий
    first_touch: bool = False
    first_personal_talk: bool = False
    first_vulnerability_shown: bool = False
    first_kiss: bool = False
    first_intimate: bool = False

    # История важных моментов
    memorable_events: List[str] = field(default_factory=list)

    @property
    def relationship_stage(self) -> RelationshipStage:
        """Определяет стадию отношений на основе метрик."""
        combined = (self.trust + self.affection) / 2
        if combined <= 20:
            return RelationshipStage.STRANGER
        elif combined <= 40:
            return RelationshipStage.ACQUAINTANCE
        elif combined <= 60:
            return RelationshipStage.COLLEAGUE
        elif combined <= 80:
            return RelationshipStage.FRIEND
        elif combined <= 90:
            return RelationshipStage.CLOSE_FRIEND
        else:
            return RelationshipStage.INTIMATE

    def to_prompt_string(self) -> str:
        """Генерирует строку состояния для включения в промпт."""
        events_text = "\n".join(f"- {event}" for event in self.memorable_events[-5:]) or "- Пока нет значимых событий"

        return f"""Уровень доверия: {self.trust}/100 ({self._trust_description()})
Привязанность: {self.affection}/100
Стадия отношений: {self.relationship_stage.value}
Текущее настроение: {self.mood.value}
Уровень возбуждения: {self.arousal}/100

Ключевые события:
{events_text}""".strip()

    def _trust_description(self) -> str:
        """Описание уровня доверия."""
        if self.trust < 30:
            return "держит дистанцию, осторожна"
        elif self.trust < 50:
            return "начинает доверять, но всё ещё настороже"
        elif self.trust < 70:
            return "доверяет, чувствует себя комфортно"
        elif self.trust < 90:
            return "глубокое доверие, готова открыться"
        else:
            return "полное доверие, абсолютная преданность"


@dataclass
class StateUpdate:
    """Результат анализа сообщения для обновления состояния."""
    trust_delta: int = 0
    affection_delta: int = 0
    arousal_delta: int = 0
    comfort_delta: int = 0
    new_mood: Mood | None = None
    event_to_remember: str | None = None
    flags_to_set: List[str] = field(default_factory=list)
