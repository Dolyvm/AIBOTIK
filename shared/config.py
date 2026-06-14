import os
from pathlib import Path

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

CONTENT_BASE_PATH = Path(os.getenv("CONTENT_PATH", "/app/content"))

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

LLM_ACTIVE_MODEL_PROMPT_KEY = "llm_active_model"
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek/deepseek-v4-flash")
STRUCTURED_MODEL = os.getenv("STRUCTURED_MODEL", "qwen/qwen3.6-flash")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", CHAT_MODEL)
PLAYER_MODEL = os.getenv("PLAYER_MODEL", CHAT_MODEL)

LLM_MODEL_CHOICES = {
    "deepseek_v4_flash": {
        "label": "DeepSeek V4 Flash",
        "model": "deepseek/deepseek-v4-flash",
    },
    "qwen3_6_flash": {
        "label": "Qwen3.6 Flash (Structured)",
        "model": "qwen/qwen3.6-flash",
    },
}
LLM_DEFAULT_PROVIDER = os.getenv("LLM_DEFAULT_PROVIDER", "deepseek_v4_flash")
LLM_DEFAULT_ACTIVE_MODEL = LLM_MODEL_CHOICES.get(
    LLM_DEFAULT_PROVIDER,
    LLM_MODEL_CHOICES["deepseek_v4_flash"],
)["model"]
LLM_MODEL = os.getenv("LLM_MODEL", CHAT_MODEL)

LLM_MAX_TOKENS_CHARACTER = 1200
LLM_MAX_TOKENS_WORLD = 1200
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.35"))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_REPETITION_PENALTY = float(os.getenv("LLM_REPETITION_PENALTY", "1.15"))

SUMMARY_THRESHOLD = 15
MAX_HISTORY_LENGTH = 10


IMAGES_STORAGE_PATH = os.getenv("IMAGES_STORAGE_PATH", "/app/generated_images")
IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost/images")  
ADMIN_TELEGRAM_IDS = [int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()]

PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET")
PLATEGA_BASE_URL = os.getenv("PLATEGA_BASE_URL", "https://app.platega.io/").rstrip("/") + "/"
