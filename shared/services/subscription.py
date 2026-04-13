"""SubscriptionService — управление подписками и трекинг использования."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import User, MonthlyUsage, SubscriptionPlan
from shared.subscription_plans import PLAN_LIMITS, USAGE_TYPE_MAP
from shared.database.repositories.subscription import SubscriptionRepository
from shared.database.exceptions import UsageLimitExceeded


class SubscriptionService:
    def __init__(self):
        pass

    def _current_period(self) -> str:
        # TODO: migrate all datetime.utcnow() to datetime.now(datetime.UTC) across the project
        return datetime.utcnow().strftime("%Y-%m")

    def _repo(self, session: AsyncSession) -> SubscriptionRepository:
        return SubscriptionRepository(session)

    async def get_user_plan(self, user: User, session: AsyncSession) -> SubscriptionPlan:
        """Проверяет expiry, даунгрейдит если истёк."""
        if user.subscription_plan == SubscriptionPlan.FREE:
            return SubscriptionPlan.FREE

        if user.subscription_end_date and user.subscription_end_date < datetime.utcnow():
            user.subscription_plan = SubscriptionPlan.FREE
            user.is_subscribed = False
            user.subscription_end_date = None
            user.subscription_start_date = None
            await session.commit()
            return SubscriptionPlan.FREE

        return user.subscription_plan

    async def check_usage_allowed(
        self, user_id: int, usage_type: str, session: AsyncSession
    ) -> tuple[bool, int, int]:
        """Проверяет лимит. Возвращает (allowed, remaining, total_limit)."""
        user = await session.get(User, user_id)
        if not user:
            return False, 0, 0

        plan = await self.get_user_plan(user, session)
        limits = PLAN_LIMITS[plan]
        plan_limit = limits.get(usage_type, 0)

        period = self._current_period()
        repo = self._repo(session)
        usage = await repo.get_monthly_usage(user_id, period)

        db_field = USAGE_TYPE_MAP.get(usage_type, usage_type)
        current = getattr(usage, db_field, 0) if usage else 0
        bonus = getattr(usage, f"bonus_{db_field}", 0) if usage else 0
        total_limit = plan_limit + bonus
        remaining = max(0, total_limit - current)

        return remaining > 0, remaining, total_limit

    async def increment_usage(
        self, user_id: int, usage_type: str, session: AsyncSession
    ) -> MonthlyUsage:
        """Атомарный инкремент с проверкой лимита в одном запросе.
        Бросает UsageLimitExceeded если лимит исчерпан."""
        user = await session.get(User, user_id)
        if not user:
            raise UsageLimitExceeded(usage_type, 0)

        plan = await self.get_user_plan(user, session)
        limits = PLAN_LIMITS[plan]
        plan_limit = limits.get(usage_type, 0)

        db_field = USAGE_TYPE_MAP.get(usage_type)
        if not db_field:
            raise ValueError(f"Unknown usage type: {usage_type}")

        period = self._current_period()
        repo = self._repo(session)
        current_usage = await repo.get_monthly_usage(user_id, period)
        bonus = getattr(current_usage, f"bonus_{db_field}", 0) if current_usage else 0
        total_limit = plan_limit + bonus

        if total_limit <= 0:
            raise UsageLimitExceeded(usage_type, total_limit)

        usage = await repo.upsert_usage(user_id, period, db_field, 1, limit=total_limit)
        if usage is None:
            raise UsageLimitExceeded(usage_type, total_limit)
        return usage

    async def activate_subscription(
        self, user_id: int, plan: SubscriptionPlan, session: AsyncSession,
        auto_commit: bool = True,
    ) -> User:
        """Активирует подписку для пользователя."""
        user = await session.get(User, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        plan_config = PLAN_LIMITS[plan]
        duration_days = plan_config["duration_days"]

        now = datetime.utcnow()
        user.subscription_plan = plan
        user.subscription_start_date = now
        user.is_subscribed = plan != SubscriptionPlan.FREE
        user.subscription_end_date = now + timedelta(days=duration_days) if duration_days else None

        if auto_commit:
            await session.commit()
            await session.refresh(user)
        return user

    async def get_usage_summary(self, user_id: int, session: AsyncSession) -> dict:
        """Возвращает сводку использования за текущий месяц."""
        user = await session.get(User, user_id)
        if not user:
            return {}

        plan = await self.get_user_plan(user, session)
        limits = PLAN_LIMITS[plan]
        period = self._current_period()
        repo = self._repo(session)
        usage = await repo.get_monthly_usage(user_id, period)

        is_unlimited = limits.get("display_as_unlimited", False)
        summary = {}
        for usage_type, db_field in USAGE_TYPE_MAP.items():
            plan_limit = limits.get(usage_type, 0)
            current = getattr(usage, db_field, 0) if usage else 0
            bonus = getattr(usage, f"bonus_{db_field}", 0) if usage else 0
            total_limit = plan_limit + bonus
            summary[usage_type] = {
                "used": current,
                "limit": -1 if is_unlimited else total_limit,
                "bonus": bonus,
                "remaining": -1 if is_unlimited else max(0, total_limit - current),
            }

        return {
            "plan": plan.value,
            "plan_display_name": limits["display_name"],
            "period": period,
            "subscription_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
            "usage": summary,
        }

    def calculate_upgrade_credit(self, user: User, new_plan: SubscriptionPlan) -> int:
        """Пропорциональный расчёт кредита при апгрейде."""
        if user.subscription_plan == SubscriptionPlan.FREE:
            return 0

        current_config = PLAN_LIMITS[user.subscription_plan]
        if not user.subscription_end_date or not user.subscription_start_date:
            return 0

        now = datetime.utcnow()
        if now >= user.subscription_end_date:
            return 0

        total_days = (user.subscription_end_date - user.subscription_start_date).days
        if total_days <= 0:
            return 0

        remaining_days = (user.subscription_end_date - now).days
        ratio = remaining_days / total_days
        credit = int(current_config["price_stars"] * ratio)
        return credit


# Singleton
_subscription_service: Optional[SubscriptionService] = None


def get_subscription_service() -> SubscriptionService:
    global _subscription_service
    if _subscription_service is None:
        _subscription_service = SubscriptionService()
    return _subscription_service


def set_subscription_service(service: SubscriptionService) -> None:
    global _subscription_service
    _subscription_service = service
