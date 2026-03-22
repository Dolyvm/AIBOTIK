
import sys
from pathlib import Path
from typing import Optional
import logging

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import Header, HTTPException, status
from telegram_init_data import validate, parse

from datetime import datetime
from shared.models import User, UserSettings
from shared.database import get_session
from shared.database.repositories import UserRepository
from shared.config import BOT_TOKEN
from shared.services.cache import get_cache

def user_to_dict(user: User) -> dict:
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "balance": user.balance,
        "is_subscribed": user.is_subscribed,
        "subscription_plan": user.subscription_plan.value if user.subscription_plan else "free",
        "subscription_start_date": user.subscription_start_date.isoformat() if user.subscription_start_date else None,
        "subscription_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
        "subscription_auto_renew": user.subscription_auto_renew,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
        "settings": {
            "nsfw_blur": user.settings.nsfw_blur if user.settings else True,
            "language": user.settings.language if user.settings else "ru",
            "nickname": user.settings.nickname if user.settings else None
        } if user.settings else None
    }

def dict_to_user(data: dict) -> User:
    from shared.models import SubscriptionPlan
    plan_value = data.get("subscription_plan", "free")
    try:
        plan = SubscriptionPlan(plan_value)
    except ValueError:
        plan = SubscriptionPlan.FREE

    user = User(
        telegram_id=data["telegram_id"],
        username=data.get("username"),
        avatar_url=data.get("avatar_url"),
        balance=data.get("balance", 1000),
        is_subscribed=data.get("is_subscribed", False),
        subscription_plan=plan,
        subscription_auto_renew=data.get("subscription_auto_renew", False),
    )

    if data.get("subscription_start_date"):
        user.subscription_start_date = datetime.fromisoformat(data["subscription_start_date"])
    if data.get("subscription_end_date"):
        user.subscription_end_date = datetime.fromisoformat(data["subscription_end_date"])
    if data.get("created_at"):
        user.created_at = datetime.fromisoformat(data["created_at"])
    if data.get("last_active_at"):
        user.last_active_at = datetime.fromisoformat(data["last_active_at"])

    if data.get("settings"):
        user.settings = UserSettings(
            user_id=data["telegram_id"],
            nsfw_blur=data["settings"].get("nsfw_blur", True),
            language=data["settings"].get("language", "ru"),
            nickname=data["settings"].get("nickname")
        )

    return user

async def get_current_user(
    authorization: Optional[str] = Header(None)
) -> User:
    logging.info(f"[AUTH] Received authorization header: {authorization[:50] if authorization else 'None'}...")

    if not authorization:
        logging.error("[AUTH] Missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "authentication_failed",
                "message": "Missing Authorization header",
                "code": "MISSING_AUTH_HEADER"
            }
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "tma":
        logging.error("[AUTH] Invalid Authorization header format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "authentication_failed",
                "message": "Invalid Authorization header format. Expected: 'tma <initData>'",
                "code": "INVALID_AUTH_FORMAT"
            }
        )

    init_data = parts[1]

    try:
        validate(init_data, BOT_TOKEN)
        parsed_data = parse(init_data)

    except Exception as e:
        error_msg = str(e)
        logging.error(f"[AUTH] Validation failed: {error_msg}")

        if "hash" in error_msg.lower() or "signature" in error_msg.lower():
            error_code = "INVALID_SIGNATURE"
        elif "expired" in error_msg.lower():
            error_code = "EXPIRED_DATA"
        elif "auth_date" in error_msg.lower():
            error_code = "MISSING_DATA"
        else:
            error_code = "VALIDATION_ERROR"

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "authentication_failed",
                "message": error_msg,
                "code": error_code
            }
        )

    user_data = parsed_data.get("user")
    if not user_data:
        logging.error("[AUTH] User data missing from parsed init data")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "authentication_failed",
                "message": "User data missing from init data",
                "code": "MISSING_DATA"
            }
        )

    telegram_id = user_data.get("id")
    if not telegram_id:
        logging.error("[AUTH] User ID missing from user data")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "authentication_failed",
                "message": "User ID missing from init data",
                "code": "MISSING_DATA"
            }
        )

    cache = get_cache()
    if cache:
        cached_user = await cache.get_user(telegram_id)
        if cached_user:
            logging.debug(f"[AUTH] User {telegram_id} found in cache")
            return dict_to_user(cached_user)

    async with get_session() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(telegram_id)

    if not user:
        logging.error(f"[AUTH] User {telegram_id} not found in database")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "user_not_found",
                "message": f"User with telegram_id {telegram_id} not found in database",
                "code": "USER_NOT_FOUND"
            }
        )

    if cache:
        await cache.set_user(telegram_id, user_to_dict(user))
    logging.info(f"[AUTH] Successfully authenticated user {telegram_id}")
    return user
