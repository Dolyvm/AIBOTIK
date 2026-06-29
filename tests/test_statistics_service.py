import asyncio

from shared.services.statistics import StatisticsService


class FakeResult:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, *, rows=None, scalar=None):
        self.rows = rows or []
        self.scalar = scalar
        self.statement = ""
        self.params = None

    async def execute(self, statement, params=None):
        self.statement = str(statement)
        self.params = params
        return FakeResult(rows=self.rows, scalar=self.scalar)


def test_users_with_chats_uses_chats_table():
    session = FakeSession(scalar=3)

    result = asyncio.run(StatisticsService.get_users_with_chats(session))

    assert result == 3
    assert "chats" in session.statement.lower()
    assert "events" not in session.statement.lower()


def test_top_characters_includes_photos_and_view_sorting():
    row = {
        "Персонаж": "Айко",
        "Просмотры": 42,
        "Чаты": 10,
        "Конверсия (%)": 23.8,
        "Сообщения": 150,
        "Фотографии": 7,
    }
    session = FakeSession(rows=[row])

    result = asyncio.run(StatisticsService.get_top_characters_info(session, head=5))

    assert result == [row]
    assert session.params == {"head": 5}
    assert "event_type = 'image_generated'" in session.statement
    assert 'AS "Фотографии"' in session.statement
    assert "WHERE COALESCE(v.views, 0) > 0" in session.statement
    assert "COALESCE(v.views, 0) DESC" in session.statement
    assert "COALESCE(cs.chats, 0) DESC" in session.statement
    assert "ch.name ASC" in session.statement


def test_inactive_users_summary_is_not_named_as_bot_blocks():
    row = {
        "Всего неактивных": 2,
        "Процент от всех пользователей": 25.0,
        "Среднее дней без активности": 12.5,
        "Всего событий от неактивных": 33,
        "Порог неактивности (дней)": 7,
        "Распределение по последним событиям": {"message_sent": 2},
    }
    session = FakeSession(rows=[row])

    result = asyncio.run(StatisticsService.get_churned_users_summary(session, days_threshold=7))

    assert result == row
    assert session.params == {"days_threshold": 7}
    assert "u.last_active_at" in session.statement
    assert "inactive_users" in session.statement
    assert '"Всего неактивных"' in session.statement
    assert "Всего ушедших" not in session.statement
