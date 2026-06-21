"""Конфигурация подписочных планов."""
from shared.models import SubscriptionPlan

MIN_PLATEGA_PAYMENT_RUB = 10
STARS_RUB_RATE = 1.4
STARS_MARKUP = 1.5

USAGE_LIMIT_KEYS = (
    "messages",
    "images_generated",
    "characters_created",
    "worlds_created",
    "content_edits",
    "avatar_generations",
)


def calculate_stars_price(price_rub: int) -> int:
    if price_rub <= 0:
        return 0
    return int(round(price_rub / STARS_RUB_RATE * STARS_MARKUP))


def is_usage_display_unlimited(plan_config: dict, usage_type: str) -> bool:
    if plan_config.get("display_as_unlimited") is True:
        return True
    return usage_type in plan_config.get("display_unlimited_usage_types", ())

PLAN_LIMITS = {
    SubscriptionPlan.FREE: {
        "display_name": "Free",
        "price_rub": 0,
        "price_stars": 0,
        "duration_days": None,
        "messages": 300,
        "images_generated": 5,
        "characters_created": 1,
        "worlds_created": 1,
        "content_edits": 5,
        "avatar_generations": 0,
    },
    SubscriptionPlan.PLUS_WEEKLY: {
        "display_name": "PLUS 1 нед",
        "price_rub": 299,
        "price_stars": calculate_stars_price(299),
        "duration_days": 7,
        "display_unlimited_usage_types": ("messages",),
        "messages": 750,
        "images_generated": 30,
        "characters_created": 2,
        "worlds_created": 2,
        "content_edits": 10,
        "avatar_generations": 10,
    },
    SubscriptionPlan.PLUS_MONTHLY: {
        "display_name": "PLUS",
        "price_rub": 799,
        "price_stars": calculate_stars_price(799),
        "duration_days": 30,
        "display_unlimited_usage_types": ("messages",),
        "messages": 3000,
        "images_generated": 120,
        "characters_created": 10,
        "worlds_created": 10,
        "content_edits": 50,
        "avatar_generations": 40,
    },
    SubscriptionPlan.PRO: {
        "display_name": "PRO",
        "price_rub": 1299,
        "price_stars": calculate_stars_price(1299),
        "duration_days": 30,
        "display_as_unlimited": True,
        "messages": 12000,
        "images_generated": 300,
        "characters_created": 50,
        "worlds_created": 50,
        "content_edits": 150,
        "avatar_generations": 150,
    },
}

# Маппинг usage_type → поле в MonthlyUsage и ключ в PLAN_LIMITS
USAGE_TYPE_MAP = {
    "messages": "messages_sent",
    "images_generated": "images_generated",
    "characters_created": "characters_created",
    "worlds_created": "worlds_created",
    "content_edits": "content_edits",
    "avatar_generations": "avatar_generations",
}
