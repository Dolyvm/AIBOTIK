import logging
import sys
from pathlib import Path

from aiogram import Router
from aiogram.types import PreCheckoutQuery, Message

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.database import get_session
from shared.database.repositories.subscription import SubscriptionRepository
from shared.services.subscription import get_subscription_service
from shared.models import SubscriptionPlan
from shared.subscription_plans import PLAN_LIMITS

logger = logging.getLogger(__name__)

router = Router()


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    """Validate Telegram Stars invoice before Telegram accepts checkout."""
    payload = query.invoice_payload
    try:
        payment_id = int(payload)
    except (ValueError, TypeError):
        logger.warning("Rejected pre-checkout with invalid payload: %r", payload)
        await query.answer(ok=False, error_message="Некорректный платёж.")
        return

    async with get_session() as session:
        repo = SubscriptionRepository(session)
        payment = await repo.get_by_id(payment_id)

    if not payment:
        logger.warning("Rejected pre-checkout for missing payment id=%s", payment_id)
        await query.answer(ok=False, error_message="Платёж не найден.")
        return

    if (
        payment.provider != "telegram_stars"
        or payment.status != "pending"
        or payment.user_id != query.from_user.id
        or payment.currency != "XTR"
        or payment.amount_stars != query.total_amount
        or query.currency != "XTR"
    ):
        logger.warning("Rejected pre-checkout for payment id=%s", payment_id)
        await query.answer(ok=False, error_message="Платёж не прошёл проверку.")
        return

    await query.answer(ok=True)


@router.message(lambda m: m.successful_payment is not None)
async def on_successful_payment(message: Message):
    """Handle successful Telegram Stars payment — activate subscription."""
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload  # payment_id
    charge_id = payment_info.telegram_payment_charge_id
    user_id = message.from_user.id

    logger.info(
        f"Payment success: user={user_id}, payload={payload}, charge={charge_id}"
    )

    try:
        payment_id = int(payload)
    except (ValueError, TypeError):
        logger.error(f"Invalid invoice_payload: {payload}")
        await message.answer("Ошибка обработки платежа. Обратитесь в поддержку.")
        return

    service = get_subscription_service()

    async with get_session() as session:
        repo = SubscriptionRepository(session)

        payment = await repo.get_by_id(payment_id)
        if not payment:
            logger.error(f"Payment {payment_id} not found")
            await message.answer("Ошибка обработки платежа. Обратитесь в поддержку.")
            return

        if payment.status == "completed":
            logger.info("Payment %s already completed", payment_id)
            await message.answer("Платёж уже был обработан.")
            return

        if (
            payment.provider != "telegram_stars"
            or payment.status != "pending"
            or payment.user_id != user_id
            or payment.currency != payment_info.currency
            or payment.amount_stars != payment_info.total_amount
            or payment_info.currency != "XTR"
        ):
            logger.error(
                "Payment validation failed: payment_id=%s provider=%s status=%s payer=%s",
                payment_id,
                payment.provider,
                payment.status,
                user_id,
            )
            await message.answer("Ошибка проверки платежа. Обратитесь в поддержку.")
            return

        # Update payment record (без commit — будет один общий)
        payment = await repo.update_payment_status(
            payment_id, status="completed", charge_id=charge_id,
            auto_commit=False,
        )

        # Activate subscription (без commit — будет один общий)
        user = await service.activate_subscription(
            user_id, payment.plan, session, auto_commit=False,
        )

        # Один commit для обеих операций — атомарно
        await session.commit()
        await session.refresh(payment)
        await session.refresh(user)

    plan_config = PLAN_LIMITS[payment.plan]
    end_date = user.subscription_end_date.strftime("%d.%m.%Y") if user.subscription_end_date else "∞"

    await message.answer(
        f"✅ Подписка {plan_config['display_name']} активирована!\n"
        f"Действует до: {end_date}\n\n"
        f"Спасибо за покупку!"
    )
