"""Репозиторий для подписок и usage-трекинга."""
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import MonthlyUsage, SubscriptionPayment, SubscriptionPlan
from .base import BaseRepository


class SubscriptionRepository(BaseRepository[SubscriptionPayment]):
    model = SubscriptionPayment

    async def get_monthly_usage(self, user_id: int, period: str) -> MonthlyUsage | None:
        result = await self.session.execute(
            select(MonthlyUsage).where(
                MonthlyUsage.user_id == user_id,
                MonthlyUsage.period == period,
            )
        )
        return result.scalar_one_or_none()

    ALLOWED_FIELDS = frozenset({
        "messages_sent", "images_generated", "characters_created",
        "worlds_created", "content_edits",
    })

    ALLOWED_BONUS_FIELDS = frozenset({
        "bonus_messages_sent", "bonus_images_generated", "bonus_characters_created",
        "bonus_worlds_created", "bonus_content_edits",
    })

    _RETURNING = """
        RETURNING id, user_id, period,
                  messages_sent, images_generated, characters_created,
                  worlds_created, content_edits,
                  bonus_messages_sent, bonus_images_generated, bonus_characters_created,
                  bonus_worlds_created, bonus_content_edits
    """

    def _row_to_usage(self, row) -> MonthlyUsage:
        return MonthlyUsage(
            id=row.id, user_id=row.user_id, period=row.period,
            messages_sent=row.messages_sent,
            images_generated=row.images_generated,
            characters_created=row.characters_created,
            worlds_created=row.worlds_created,
            content_edits=row.content_edits,
            bonus_messages_sent=row.bonus_messages_sent,
            bonus_images_generated=row.bonus_images_generated,
            bonus_characters_created=row.bonus_characters_created,
            bonus_worlds_created=row.bonus_worlds_created,
            bonus_content_edits=row.bonus_content_edits,
        )

    async def upsert_usage(self, user_id: int, period: str, field: str, increment: int = 1, limit: int | None = None) -> MonthlyUsage | None:
        """Атомарный upsert usage через ON CONFLICT DO UPDATE.

        Если limit передан, инкремент произойдёт только если текущее значение < limit.
        Возвращает None если лимит превышен.
        """
        if field not in self.ALLOWED_FIELDS:
            raise ValueError(f"Invalid usage field: {field}")

        if limit is not None:
            stmt = text("""
                INSERT INTO monthly_usage (user_id, period, {field})
                VALUES (:user_id, :period, :increment)
                ON CONFLICT ON CONSTRAINT uq_monthly_usage_user_period
                DO UPDATE SET {field} = monthly_usage.{field} + :increment
                WHERE monthly_usage.{field} < :limit
            """.format(field=field) + self._RETURNING)
            result = await self.session.execute(stmt, {
                "user_id": user_id, "period": period,
                "increment": increment, "limit": limit,
            })
        else:
            stmt = text("""
                INSERT INTO monthly_usage (user_id, period, {field})
                VALUES (:user_id, :period, :increment)
                ON CONFLICT ON CONSTRAINT uq_monthly_usage_user_period
                DO UPDATE SET {field} = monthly_usage.{field} + :increment
            """.format(field=field) + self._RETURNING)
            result = await self.session.execute(stmt, {
                "user_id": user_id, "period": period, "increment": increment,
            })

        row = result.fetchone()
        await self.session.commit()

        if row is None:
            return None

        return self._row_to_usage(row)

    async def set_bonus_limits(self, user_id: int, period: str, bonuses: dict[str, int]) -> None:
        """Прибавляет бонусные лимиты пользователю за указанный период.

        bonuses = {"bonus_messages_sent": 100, "bonus_characters_created": 2, ...}
        Создаёт запись если её нет, иначе прибавляет к существующим бонусам.
        """
        if not bonuses:
            return
        for key in bonuses:
            if key not in self.ALLOWED_BONUS_FIELDS:
                raise ValueError(f"Invalid bonus field: {key}")

        set_parts = ", ".join(
            f"{field} = COALESCE(monthly_usage.{field}, 0) + :{field}"
            for field in bonuses
        )
        stmt = text(f"""
            INSERT INTO monthly_usage (user_id, period)
            VALUES (:user_id, :period)
            ON CONFLICT ON CONSTRAINT uq_monthly_usage_user_period
            DO UPDATE SET {set_parts}
        """)
        params = {"user_id": user_id, "period": period, **bonuses}
        await self.session.execute(stmt, params)
        await self.session.commit()

    async def create_payment(
        self,
        user_id: int,
        plan: SubscriptionPlan,
        amount_stars: int,
        amount_rub: int,
        provider: str = "telegram_stars",
        currency: str = "XTR",
        provider_payment_id: str | None = None,
        provider_payment_url: str | None = None,
        provider_payload: dict | None = None,
    ) -> SubscriptionPayment:
        payment = SubscriptionPayment(
            user_id=user_id,
            plan=plan,
            amount_stars=amount_stars,
            amount_rub=amount_rub,
            provider=provider,
            currency=currency,
            provider_payment_id=provider_payment_id,
            provider_payment_url=provider_payment_url,
            provider_payload=provider_payload,
            status="pending",
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def update_payment_status(
        self, payment_id: int, status: str, charge_id: str | None = None,
        provider_payload: dict | None = None,
        auto_commit: bool = True,
    ) -> SubscriptionPayment | None:
        payment = await self.get_by_id(payment_id)
        if not payment:
            return None
        payment.status = status
        if charge_id:
            payment.telegram_payment_charge_id = charge_id
        if provider_payload is not None:
            payment.provider_payload = provider_payload
        if status == "completed":
            payment.completed_at = datetime.utcnow()
        if auto_commit:
            await self.session.commit()
            await self.session.refresh(payment)
        return payment

    async def update_payment_provider_fields(
        self,
        payment_id: int,
        provider_payment_id: str | None = None,
        provider_payment_url: str | None = None,
        provider_payload: dict | None = None,
        auto_commit: bool = True,
    ) -> SubscriptionPayment | None:
        payment = await self.get_by_id(payment_id)
        if not payment:
            return None
        if provider_payment_id is not None:
            payment.provider_payment_id = provider_payment_id
        if provider_payment_url is not None:
            payment.provider_payment_url = provider_payment_url
        if provider_payload is not None:
            payment.provider_payload = provider_payload
        if auto_commit:
            await self.session.commit()
            await self.session.refresh(payment)
        return payment

    async def get_by_provider_payment_id(
        self, provider: str, provider_payment_id: str
    ) -> SubscriptionPayment | None:
        result = await self.session.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.provider == provider,
                SubscriptionPayment.provider_payment_id == provider_payment_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_completed_payment(self, user_id: int) -> SubscriptionPayment | None:
        result = await self.session.execute(
            select(SubscriptionPayment)
            .where(
                SubscriptionPayment.user_id == user_id,
                SubscriptionPayment.status == "completed",
            )
            .order_by(SubscriptionPayment.completed_at.desc(), SubscriptionPayment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_user_payments(self, user_id: int, limit: int = 50) -> list[SubscriptionPayment]:
        result = await self.session.execute(
            select(SubscriptionPayment)
            .where(SubscriptionPayment.user_id == user_id)
            .order_by(SubscriptionPayment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
