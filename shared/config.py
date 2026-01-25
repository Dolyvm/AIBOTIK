import os
from pathlib import Path

BOT_TOKEN = os.getenv("BOT_TOKEN")

CONTENT_BASE_PATH = Path(os.getenv("CONTENT_PATH", "/app/content"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rpbot:popa@localhost:5432/rpbot"
)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "mistralai/mistral-small-creative"

LLM_MAX_TOKENS_CHARACTER = 200  
LLM_MAX_TOKENS_WORLD = 400     
LLM_TEMPERATURE = 0.8
LLM_TOP_P = 0.9
LLM_REPETITION_PENALTY = 1.15

SUMMARY_THRESHOLD = 15
MAX_HISTORY_LENGTH = 10


SCENE_ANALYZER_ENABLED = os.getenv("SCENE_ANALYZER_ENABLED", "true").lower() == "true"
SCENE_ANALYZER_MODEL = os.getenv("SCENE_ANALYZER_MODEL", "mistralai/mistral-small-creative") 
SCENE_ANALYZER_TIMEOUT = int(os.getenv("SCENE_ANALYZER_TIMEOUT", "10"))  

IMAGES_STORAGE_PATH = os.getenv("IMAGES_STORAGE_PATH", "/app/generated_images")
IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost/images")  