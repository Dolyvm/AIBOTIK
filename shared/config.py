import os
from pathlib import Path

BOT_TOKEN = os.getenv("BOT_TOKEN")

CONTENT_BASE_PATH = Path(os.getenv("CONTENT_PATH", "/app/content"))

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "mistralai/voxtral-small-24b-2507"

LLM_MAX_TOKENS_CHARACTER = 1200
LLM_MAX_TOKENS_WORLD = 1200
LLM_TEMPERATURE = 0.8
LLM_TOP_P = 0.9
LLM_REPETITION_PENALTY = 1.15

SUMMARY_THRESHOLD = 15
MAX_HISTORY_LENGTH = 10


SCENE_ANALYZER_ENABLED = os.getenv("SCENE_ANALYZER_ENABLED", "true").lower() == "true"
SCENE_ANALYZER_MODEL = os.getenv("SCENE_ANALYZER_MODEL", "mistralai/voxtral-small-24b-2507") 
SCENE_ANALYZER_TIMEOUT = int(os.getenv("SCENE_ANALYZER_TIMEOUT", "10"))
STRUCTURED_MODEL = os.getenv("STRUCTURED_MODEL", "qwen/qwen3-30b-a3b-instruct-2507")

IMAGES_STORAGE_PATH = os.getenv("IMAGES_STORAGE_PATH", "/app/generated_images")
IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost/images")  
ADMIN_TELEGRAM_IDS = [int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()]
