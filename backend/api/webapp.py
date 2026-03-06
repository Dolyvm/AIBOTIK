import logging

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from telegram_init_data import validate, parse

from shared.config import BOT_TOKEN
from shared.services.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webapp", tags=["webapp"])

STICKER_FILE_ID = "CAACAgIAAxkBAAEQsYtpqy4hWTZUbnvY1JAQMHDdQJm_8gACw5sAAkvrOElcdhNJ3GG0RDoE"
BOT_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_close_sticker(telegram_id: int):
    redis = await get_redis()
    redis_key = f"sticker_msg:{telegram_id}"

    async with httpx.AsyncClient() as client:
        prev_msg_id = await redis.get(redis_key)
        if prev_msg_id:
            try:
                await client.post(f"{BOT_API_URL}/deleteMessage", json={
                    "chat_id": telegram_id,
                    "message_id": int(prev_msg_id),
                })
            except Exception as e:
                logger.warning(f"Failed to delete previous sticker for {telegram_id}: {e}")

        try:
            resp = await client.post(f"{BOT_API_URL}/sendSticker", json={
                "chat_id": telegram_id,
                "sticker": STICKER_FILE_ID,
            })
            data = resp.json()
            if data.get("ok"):
                new_msg_id = data["result"]["message_id"]
                await redis.set(redis_key, str(new_msg_id))
        except Exception as e:
            logger.error(f"Failed to send sticker to {telegram_id}: {e}")


@router.websocket("/ws")
async def webapp_ws(websocket: WebSocket):
    init_data = websocket.query_params.get("initData")
    if not init_data:
        await websocket.close(code=1008)
        return

    try:
        validate(init_data, BOT_TOKEN)
        parsed = parse(init_data)
    except Exception:
        await websocket.close(code=1008)
        return

    user_data = parsed.get("user")
    telegram_id = user_data.get("id") if user_data else None
    if not telegram_id:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info(f"WebApp WS connected: user {telegram_id}")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        logger.info(f"WebApp WS disconnected: user {telegram_id}, sending sticker")
        await send_close_sticker(telegram_id)
