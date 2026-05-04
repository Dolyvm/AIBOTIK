from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from shared.models import User, SubscriptionPlan
from shared.subscription_plans import PLAN_LIMITS
from shared.database import get_session
from shared.database.repositories.subscription import SubscriptionRepository
from shared.services.subscription import get_subscription_service
from shared.config import BOT_TOKEN
from auth.telegram_auth import get_current_user

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


class PurchaseRequest(BaseModel):
    plan: str


@router.get("/plans")
async def get_plans():
    """Список планов с ценами и лимитами (без auth)."""
    plans = []
    for plan_enum, config in PLAN_LIMITS.items():
        plans.append({
            "plan": plan_enum.value,
            "display_name": config["display_name"],
            "price_rub": config["price_rub"],
            "price_stars": config["price_stars"],
            "duration_days": config["duration_days"],
            "limits": {
                k: -1 if config.get("display_as_unlimited") else config[k]
                for k in ["messages", "images", "characters_created", "worlds_created", "content_edits", "avatar_generations"]
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
    """Создаёт payment, возвращает invoice data для Telegram Stars."""
    try:
        plan = SubscriptionPlan(payload.plan)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid plan: {payload.plan}")

    if plan == SubscriptionPlan.FREE:
        raise HTTPException(status_code=400, detail="Cannot purchase free plan")

    plan_config = PLAN_LIMITS[plan]
    service = get_subscription_service()

    async with get_session() as session:
        db_user = await session.get(User, user.telegram_id)
        credit = service.calculate_upgrade_credit(db_user, plan)
        final_price = max(1, plan_config["price_stars"] - credit)
        # Пропорционально пересчитываем рубли при наличии кредита
        if credit > 0 and plan_config["price_stars"] > 0:
            final_rub = max(0, int(plan_config["price_rub"] * final_price / plan_config["price_stars"]))
        else:
            final_rub = plan_config["price_rub"]

        repo = SubscriptionRepository(session)
        payment = await repo.create_payment(
            user_id=user.telegram_id,
            plan=plan,
            amount_stars=final_price,
            amount_rub=final_rub,
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink",
            json={
                "title": f"Подписка {plan_config['display_name']}",
                "description": f"Подписка на {plan_config.get('duration_days', 30)} дней",
                "payload": str(payment.id),
                "currency": "XTR",
                "prices": [{"label": "Подписка", "amount": final_price}],
            },
        )
        data = resp.json()
        if not data.get("ok"):
            raise HTTPException(status_code=500, detail=f"Telegram API error: {data.get('description')}")
        invoice_url = data["result"]

    return {
        "payment_id": payment.id,
        "invoice_url": invoice_url,
        "plan": plan.value,
        "display_name": plan_config["display_name"],
        "amount_stars": final_price,
        "upgrade_credit": credit,
    }


@router.post("/auto-renew")
async def enable_auto_renew(user: User = Depends(get_current_user)):
    """Включает auto_renew."""
    async with get_session() as session:
        db_user = await session.get(User, user.telegram_id)
        if not db_user or db_user.subscription_plan == SubscriptionPlan.FREE:
            raise HTTPException(status_code=400, detail="No active subscription")

        db_user.subscription_auto_renew = True
        await session.commit()

    return {"success": True, "message": "Auto-renewal enabled."}


@router.post("/cancel")
async def cancel_subscription(user: User = Depends(get_current_user)):
    """Ставит auto_renew=false."""
    async with get_session() as session:
        db_user = await session.get(User, user.telegram_id)
        if not db_user or db_user.subscription_plan == SubscriptionPlan.FREE:
            return {"success": True, "message": "No active subscription"}

        db_user.subscription_auto_renew = False
        end_date = db_user.subscription_end_date
        await session.commit()

    return {
        "success": True,
        "message": "Auto-renewal disabled. Subscription active until end date.",
        "subscription_end_date": end_date.isoformat() if end_date else None,
    }
