"""Telegram WebApp authentication using telegram-init-data library."""

import sys
from pathlib import Path
from typing import Optional
import logging

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import Header, HTTPException, status
from telegram_init_data import validate, parse

from shared.models import User
from shared.database import get_session
from shared.database.repositories import UserRepository
from shared.config import BOT_TOKEN


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

    logging.info(f"[AUTH] Successfully authenticated user {telegram_id}")
    return user
