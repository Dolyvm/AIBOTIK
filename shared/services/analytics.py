from shared.models import Event
from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsService:

    @staticmethod
    async def track(
        db: AsyncSession,
        user_id: int,
        event_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        meta: dict | None = None,
    ):
        event = Event(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            meta=meta or {},
        )

        db.add(event)
        await db.commit()  # todo на больших объемах нужно будет коммитить батчами, щас похуй
