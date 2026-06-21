import hmac
import logging
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth.telegram_auth import get_current_user
from shared.config import BOT_TOKEN, PLATEGA_MERCHANT_ID, PLATEGA_SECRET, WEBAPP_URL
from shared.database import get_session
from shared.database.repositories.subscription import SubscriptionRepository
from shared.models import SubscriptionPlan, User
from shared.services.platega import PlategaAPIError, PlategaClient, PlategaConfigurationError
from shared.services.subscription import get_subscription_service
from shared.subscription_plans import (
    MIN_PLATEGA_PAYMENT_RUB,
    PLAN_LIMITS,
    USAGE_LIMIT_KEYS,
    is_usage_display_unlimited,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])

TELEGRAM_STARS_PROVIDER = "telegram_stars"
PLATEGA_PROVIDER = "platega"
SUPPORTED_PAYMENT_PROVIDERS = {TELEGRAM_STARS_PROVIDER, PLATEGA_PROVIDER}


class PurchaseRequest(BaseModel):
    plan: str
    provider: str = TELEGRAM_STARS_PROVIDER


class PlategaCallbackPayload(BaseModel):
    id: str
    amount: int | float | str
    currency: str
    status: str
    paymentMethod: int | str | None = None


def _parse_plan(plan_value: str) -> SubscriptionPlan:
    try:
        return SubscriptionPlan(plan_value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid plan: {plan_value}")


def _normalize_provider(provider: str | None) -> str:
    normalized = (provider or TELEGRAM_STARS_PROVIDER).lower()
    if normalized not in SUPPORTED_PAYMENT_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Invalid payment provider: {provider}")
    return normalized


def _calculate_purchase_amounts(user: User, plan: SubscriptionPlan) -> tuple[int, int, int]:
    service = get_subscription_service()
    plan_config = PLAN_LIMITS[plan]
    credit = service.calculate_upgrade_credit(user, plan)
    final_stars = max(1, plan_config["price_stars"] - credit)
    if credit > 0 and plan_config["price_stars"] > 0:
        final_rub = max(0, int(plan_config["price_rub"] * final_stars / plan_config["price_stars"]))
    else:
        final_rub = plan_config["price_rub"]
    return final_stars, final_rub, credit


def _require_public_webapp_url() -> str:
    if not WEBAPP_URL or not WEBAPP_URL.startswith("https://"):
        logger.error("WEBAPP_URL must be configured as public HTTPS URL for Platega payments")
        raise HTTPException(status_code=500, detail="Payment provider is not configured")
    return WEBAPP_URL.rstrip("/")


def _amount_matches(actual: object, expected: int) -> bool:
    try:
        return Decimal(str(actual)) == Decimal(expected)
    except (InvalidOperation, TypeError, ValueError):
        return False


def _headers_match(value: str | None, expected: str | None) -> bool:
    if not value or not expected:
        return False
    return hmac.compare_digest(value, expected)


def _validate_platega_callback_headers(x_merchant_id: str | None, x_secret: str | None) -> None:
    if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
        logger.error("Platega callback received but credentials are not configured")
        raise HTTPException(status_code=503, detail="Payment provider is not configured")
    if not (
        _headers_match(x_merchant_id, PLATEGA_MERCHANT_ID)
        and _headers_match(x_secret, PLATEGA_SECRET)
    ):
        logger.warning("Rejected Platega callback with invalid authentication headers")
        raise HTTPException(status_code=401, detail="Invalid payment callback credentials")


def _callback_payload(callback: PlategaCallbackPayload, **extra) -> dict:
    return {"callback": callback.model_dump(mode="json"), **extra}


@router.get("/plans")
async def get_plans():
    """Список планов с ценами и лимитами (без auth)."""
    plans = []
    for plan_enum, config in PLAN_LIMITS.items():
        price_rub = config["price_rub"]
        platega_price_rub = 0 if price_rub <= 0 else max(
            MIN_PLATEGA_PAYMENT_RUB,
            int(config.get("platega_price_rub", price_rub)),
        )
        plans.append({
            "plan": plan_enum.value,
            "display_name": config["display_name"],
            "price_rub": price_rub,
            "platega_price_rub": platega_price_rub,
            "price_stars": config["price_stars"],
            "duration_days": config["duration_days"],
            "limits": {
                k: -1 if is_usage_display_unlimited(config, k) else config[k]
                for k in USAGE_LIMIT_KEYS
            },
        })
    return {"plans": plans}


@router.get("/status")
async def get_status(user: User = Depends(get_current_user)):
    """Текущий план, даты, использование."""
    service = get_subscription_service()
    async with get_session() as session:
        summary = await service.get_usage_summary(user.telegram_id, session)
    return summary


@router.post("/purchase")
async def purchase_subscription(
    payload: PurchaseRequest,
    user: User = Depends(get_current_user),
):
    """Создаёт payment и возвращает данные для выбранного провайдера оплаты."""
    plan = _parse_plan(payload.plan)
    provider = _normalize_provider(payload.provider)

    if plan == SubscriptionPlan.FREE:
        raise HTTPException(status_code=400, detail="Cannot purchase free plan")

    plan_config = PLAN_LIMITS[plan]

    async with get_session() as session:
        db_user = await session.get(User, user.telegram_id)
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        final_stars, final_rub, credit = _calculate_purchase_amounts(db_user, plan)
        repo = SubscriptionRepository(session)

        if provider == TELEGRAM_STARS_PROVIDER:
            payment = await repo.create_payment(
                user_id=user.telegram_id,
                plan=plan,
                amount_stars=final_stars,
                amount_rub=final_rub,
                provider=TELEGRAM_STARS_PROVIDER,
                currency="XTR",
            )
        else:
            platega_price_rub = max(
                MIN_PLATEGA_PAYMENT_RUB,
                final_rub,
            )
            payment = await repo.create_payment(
                user_id=user.telegram_id,
                plan=plan,
                amount_stars=final_stars,
                amount_rub=platega_price_rub,
                provider=PLATEGA_PROVIDER,
                currency="RUB",
            )

    if provider == TELEGRAM_STARS_PROVIDER:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink",
                json={
                    "title": f"Подписка {plan_config['display_name']}",
                    "description": f"Подписка на {plan_config.get('duration_days', 30)} дней",
                    "payload": str(payment.id),
                    "currency": "XTR",
                    "prices": [{"label": "Подписка", "amount": final_stars}],
                },
            )
            data = resp.json()

        if not data.get("ok"):
            async with get_session() as session:
                repo = SubscriptionRepository(session)
                await repo.update_payment_status(payment.id, status="failed")
            raise HTTPException(status_code=500, detail="Telegram payment provider error")

        invoice_url = data["result"]
        return {
            "payment_id": payment.id,
            "invoice_url": invoice_url,
            "plan": plan.value,
            "display_name": plan_config["display_name"],
            "amount_stars": final_stars,
            "upgrade_credit": credit,
            "provider": TELEGRAM_STARS_PROVIDER,
        }

    base_url = _require_public_webapp_url()
    try:
        platega_response = await PlategaClient().create_payment_link(
            amount_rub=payment.amount_rub,
            description=f"Подписка {plan_config['display_name']}",
            return_url=f"{base_url}/?payment=success",
            failed_url=f"{base_url}/?payment=failed",
            payload=str(payment.id),
        )
    except PlategaConfigurationError:
        logger.exception("Platega is not configured")
        async with get_session() as session:
            repo = SubscriptionRepository(session)
            await repo.update_payment_status(payment.id, status="failed")
        raise HTTPException(status_code=500, detail="Payment provider is not configured")
    except PlategaAPIError:
        logger.exception("Platega create payment failed")
        async with get_session() as session:
            repo = SubscriptionRepository(session)
            await repo.update_payment_status(payment.id, status="failed")
        raise HTTPException(status_code=502, detail="Payment provider error")

    payment_url = platega_response.get("url") or platega_response.get("redirect")
    transaction_id = platega_response["transactionId"]
    async with get_session() as session:
        repo = SubscriptionRepository(session)
        await repo.update_payment_provider_fields(
            payment.id,
            provider_payment_id=transaction_id,
            provider_payment_url=payment_url,
            provider_payload={"create_response": platega_response},
        )

    return {
        "payment_id": payment.id,
        "payment_url": payment_url,
        "plan": plan.value,
        "display_name": plan_config["display_name"],
        "amount_rub": payment.amount_rub,
        "upgrade_credit": credit,
        "provider": PLATEGA_PROVIDER,
        "expires_in": platega_response.get("expiresIn"),
    }


@router.post("/platega/callback")
async def platega_callback(
    payload: PlategaCallbackPayload,
    x_merchant_id: str | None = Header(default=None, alias="X-MerchantId"),
    x_secret: str | None = Header(default=None, alias="X-Secret"),
):
    """Webhook endpoint for Platega transaction status changes."""
    _validate_platega_callback_headers(x_merchant_id, x_secret)

    status = payload.status.upper()
    if status == "CONFIRMED":
        return await _handle_platega_confirmed(payload)
    if status == "CANCELED":
        return await _handle_platega_terminal_status(payload, "canceled")
    if status == "CHARGEBACKED":
        return await _handle_platega_chargeback(payload)

    raise HTTPException(status_code=400, detail="Unsupported payment status")


async def _handle_platega_confirmed(callback: PlategaCallbackPayload) -> dict:
    try:
        transaction = await PlategaClient().get_transaction(callback.id)
    except (PlategaConfigurationError, PlategaAPIError):
        logger.exception("Platega transaction verification failed")
        raise HTTPException(status_code=502, detail="Payment provider verification failed")

    transaction_status = str(transaction.get("status", "")).upper()
    if transaction_status != "CONFIRMED":
        raise HTTPException(status_code=409, detail="Payment is not confirmed by provider")

    transaction_payload = transaction.get("payload")
    try:
        payment_id = int(transaction_payload)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Payment callback payload is invalid")

    payment_details = transaction.get("paymentDetails") or {}
    provider_payload = _callback_payload(callback, status_check=transaction)
    service = get_subscription_service()

    async with get_session() as session:
        repo = SubscriptionRepository(session)
        payment = await repo.get_by_id(payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        if payment.status == "completed":
            return {"success": True}

        if payment.status != "pending":
            logger.warning("Platega confirmed non-pending payment id=%s status=%s", payment.id, payment.status)
            raise HTTPException(status_code=409, detail="Payment is not pending")

        if (
            payment.provider != PLATEGA_PROVIDER
            or payment.provider_payment_id != callback.id
            or payment.currency != "RUB"
            or not _amount_matches(callback.amount, payment.amount_rub)
            or not _amount_matches(payment_details.get("amount"), payment.amount_rub)
            or str(callback.currency).upper() != "RUB"
            or str(payment_details.get("currency", "")).upper() != "RUB"
        ):
            logger.warning("Rejected Platega confirmation for mismatched payment id=%s", payment.id)
            raise HTTPException(status_code=400, detail="Payment verification failed")

        await repo.update_payment_status(
            payment.id,
            status="completed",
            provider_payload=provider_payload,
            auto_commit=False,
        )
        await service.activate_subscription(
            payment.user_id,
            payment.plan,
            session,
            auto_commit=False,
        )
        await session.commit()

    return {"success": True}


async def _handle_platega_terminal_status(
    callback: PlategaCallbackPayload, local_status: str
) -> dict:
    async with get_session() as session:
        repo = SubscriptionRepository(session)
        payment = await repo.get_by_provider_payment_id(PLATEGA_PROVIDER, callback.id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        if payment.status == "completed":
            logger.warning("Ignoring Platega %s for already completed payment id=%s", local_status, payment.id)
            return {"success": True}

        if payment.status != local_status:
            await repo.update_payment_status(
                payment.id,
                status=local_status,
                provider_payload=_callback_payload(callback),
                auto_commit=False,
            )
            await session.commit()

    return {"success": True}


async def _handle_platega_chargeback(callback: PlategaCallbackPayload) -> dict:
    async with get_session() as session:
        repo = SubscriptionRepository(session)
        payment = await repo.get_by_provider_payment_id(PLATEGA_PROVIDER, callback.id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        if payment.status == "chargebacked":
            return {"success": True}

        was_completed = payment.status == "completed"
        latest_completed = await repo.get_latest_completed_payment(payment.user_id)
        await repo.update_payment_status(
            payment.id,
            status="chargebacked",
            provider_payload=_callback_payload(callback),
            auto_commit=False,
        )

        user = await session.get(User, payment.user_id)
        should_revoke = (
            was_completed
            and latest_completed is not None
            and latest_completed.id == payment.id
            and user is not None
            and user.subscription_plan == payment.plan
        )
        if should_revoke:
            user.subscription_plan = SubscriptionPlan.FREE
            user.is_subscribed = False
            user.subscription_start_date = None
            user.subscription_end_date = None
        else:
            logger.warning("Platega chargeback requires manual review for payment id=%s", payment.id)

        await session.commit()

    return {"success": True}
