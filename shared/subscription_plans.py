"""Конфигурация подписочных планов."""
from shared.models import SubscriptionPlan

PLAN_LIMITS = {
    SubscriptionPlan.FREE: {
        "display_name": "Free",
        "price_rub": 0,
        "price_stars": 0,
        "duration_days": None,
        "messages": 300,
        "images": 5,
        "characters_created": 1,
        "worlds_created": 1,
        "content_edits": 5,
        "avatar_generations": 2,
    },
    SubscriptionPlan.PLUS_WEEKLY: {
        "display_name": "PLUS 1 нед",
        "price_rub": 299,
        "price_stars": 299,
        "duration_days": 7,
        "messages": 750,
        "images": 35,
        "characters_created": 2,
        "worlds_created": 2,
        "content_edits": 10,
        "avatar_generations": 2,
    },
    SubscriptionPlan.PLUS_MONTHLY: {
        "display_name": "PLUS",
        "price_rub": 799,
        "price_stars": 799,
        "duration_days": 30,
        "messages": 3000,
        "images": 150,
        "characters_created": 10,
        "worlds_created": 10,
        "content_edits": 50,
        "avatar_generations": 5,
    },
    SubscriptionPlan.PRO: {
        "display_name": "PRO",
        "price_rub": 1299,
        "price_stars": 1299,
        "duration_days": 30,
        "messages": 9999,
        "images": 9999,
        "characters_created": 9999,
        "worlds_created": 9999,
        "content_edits": 9999,
        "avatar_generations": 9999,
    },
}

# Маппинг usage_type → поле в MonthlyUsage и ключ в PLAN_LIMITS
USAGE_TYPE_MAP = {
    "messages": "messages_sent",
    "images": "images_generated",
    "characters_created": "characters_created",
    "worlds_created": "worlds_created",
    "content_edits": "content_edits",
    "avatar_generations": "avatar_generations",
}
