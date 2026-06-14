import logging
import os
from datetime import datetime

from aiogram import Bot
from sqlalchemy import select, update

from shared.models import SubscriptionPlan, User

logger = logging.getLogger(__name__)


async def expire_subscriptions_task(ctx: dict) -> dict:
    """Cron: downgrade expired subscriptions to FREE and notify users."""
    get_session = ctx.get("get_session")
    if not get_session:
        logger.error("expire_subscriptions_task: no get_session in context")
        return {"status": "failed"}

    expired_user_ids = []
    async with get_session() as session:
        result = await session.execute(
            select(User.telegram_id, User.subscription_plan).where(
                User.subscription_end_date < datetime.utcnow(),
                User.subscription_plan != SubscriptionPlan.FREE,
            )
        )
        expired_users = result.all()
        expired_user_ids = [row[0] for row in expired_users]

        if not expired_user_ids:
            logger.info("expire_subscriptions: no expired subscriptions found")
            return {"status": "ok", "expired": 0}

        await session.execute(
            update(User)
            .where(
                User.subscription_end_date < datetime.utcnow(),
                User.subscription_plan != SubscriptionPlan.FREE,
            )
            .values(
                subscription_plan=SubscriptionPlan.FREE,
                is_subscribed=False,
                subscription_end_date=None,
                subscription_start_date=None,
            )
        )
        await session.commit()

    bot_token = os.getenv("BOT_TOKEN")
    if bot_token and expired_user_ids:
        bot = Bot(token=bot_token)
        try:
            for uid in expired_user_ids:
                try:
                    await bot.send_message(
                        uid,
                        "Ваша подписка истекла. Вы переведены на план Free.\n"
                        "Чтобы продлить, откройте приложение и выберите план.",
                    )
                except Exception as e:
                    logger.warning("Failed to notify user %s: %s", uid, e)
        finally:
            await bot.session.close()

    logger.info("expire_subscriptions: downgraded %s users", len(expired_user_ids))
    return {"status": "ok", "expired": len(expired_user_ids)}
