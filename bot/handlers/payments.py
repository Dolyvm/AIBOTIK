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
    """Always approve pre-checkout — validation already done at invoice creation."""
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

        # Update payment record (без commit — будет один общий)
        payment = await repo.update_payment_status(
            payment_id, status="completed", charge_id=charge_id,
            auto_commit=False,
        )
        if not payment:
            logger.error(f"Payment {payment_id} not found")
            await message.answer("Ошибка обработки платежа. Обратитесь в поддержку.")
            return

        if payment.user_id != user_id:
            logger.error(f"Payment user mismatch: payment.user_id={payment.user_id}, payer={user_id}")
            await message.answer("Ошибка: этот платёж принадлежит другому пользователю.")
            return

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
