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
        "worlds_created", "content_edits", "avatar_generations",
    })

    async def upsert_usage(self, user_id: int, period: str, field: str, increment: int = 1, limit: int | None = None) -> MonthlyUsage | None:
        """Атомарный upsert usage через ON CONFLICT DO UPDATE.

        Если limit передан, инкремент произойдёт только если текущее значение < limit.
        Возвращает None если лимит превышен.
        """
        if field not in self.ALLOWED_FIELDS:
            raise ValueError(f"Invalid usage field: {field}")

        if limit is not None:
            # Атомарная проверка лимита + инкремент в одном запросе
            stmt = text("""
                INSERT INTO monthly_usage (user_id, period, {field})
                VALUES (:user_id, :period, :increment)
                ON CONFLICT ON CONSTRAINT uq_monthly_usage_user_period
                DO UPDATE SET {field} = monthly_usage.{field} + :increment
                WHERE monthly_usage.{field} < :limit
                RETURNING id, user_id, period, messages_sent, images_generated,
                          characters_created, worlds_created, content_edits, avatar_generations
            """.format(field=field))
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
                RETURNING id, user_id, period, messages_sent, images_generated,
                          characters_created, worlds_created, content_edits, avatar_generations
            """.format(field=field))
            result = await self.session.execute(stmt, {
                "user_id": user_id, "period": period, "increment": increment,
            })

        row = result.fetchone()
        await self.session.commit()

        if row is None:
            return None

        usage = MonthlyUsage(
            id=row.id, user_id=row.user_id, period=row.period,
            messages_sent=row.messages_sent, images_generated=row.images_generated,
            characters_created=row.characters_created, worlds_created=row.worlds_created,
            content_edits=row.content_edits, avatar_generations=row.avatar_generations,
        )
        return usage

    async def create_payment(
        self,
        user_id: int,
        plan: SubscriptionPlan,
        amount_stars: int,
        amount_rub: int,
    ) -> SubscriptionPayment:
        payment = SubscriptionPayment(
            user_id=user_id,
            plan=plan,
            amount_stars=amount_stars,
            amount_rub=amount_rub,
            status="pending",
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def update_payment_status(
        self, payment_id: int, status: str, charge_id: str | None = None,
        auto_commit: bool = True,
    ) -> SubscriptionPayment | None:
        payment = await self.get_by_id(payment_id)
        if not payment:
            return None
        payment.status = status
        if charge_id:
            payment.telegram_payment_charge_id = charge_id
        if status == "completed":
            payment.completed_at = datetime.utcnow()
        if auto_commit:
            await self.session.commit()
            await self.session.refresh(payment)
        return payment

    async def get_user_payments(self, user_id: int, limit: int = 50) -> list[SubscriptionPayment]:
        result = await self.session.execute(
            select(SubscriptionPayment)
            .where(SubscriptionPayment.user_id == user_id)
            .order_by(SubscriptionPayment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
