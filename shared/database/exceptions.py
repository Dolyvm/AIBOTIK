"""Типизированные исключения для БД."""
from typing import Any


class DatabaseError(Exception):
    """Базовый класс для ошибок БД."""
    pass


class EntityNotFoundError(DatabaseError):
    def __init__(self, entity_type: str, entity_id: Any):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.message = f"{entity_type} with id '{entity_id}' not found"
        super().__init__(self.message)


class ValidationError(DatabaseError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class InsufficientBalanceError(DatabaseError):
    def __init__(self, current: int, required: int):
        self.current = current
        self.required = required
        self.message = f"Insufficient balance: {current}, required: {required}"
        super().__init__(self.message)


class UsageLimitExceeded(DatabaseError):
    def __init__(self, usage_type: str, limit: int):
        self.usage_type = usage_type
        self.limit = limit
        self.message = f"Monthly limit exceeded for {usage_type}: {limit}"
        super().__init__(self.message)
