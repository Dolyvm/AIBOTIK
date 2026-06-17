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
OPENROUTER_IDENTITY_MODEL = os.getenv("OPENROUTER_IDENTITY_MODEL", "google/gemini-2.5-flash")
OPENROUTER_IDENTITY_TIMEOUT_SECONDS = int(os.getenv("OPENROUTER_IDENTITY_TIMEOUT_SECONDS", "60"))

LLM_ACTIVE_MODEL_PROMPT_KEY = "llm_active_model"
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek/deepseek-v4-flash")
STRUCTURED_MODEL = os.getenv("STRUCTURED_MODEL", "qwen/qwen3.6-flash")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", CHAT_MODEL)
PLAYER_MODEL = os.getenv("PLAYER_MODEL", CHAT_MODEL)
LLM_CHAT_PROVIDER_ROUTING = {"sort": "throughput", "ignore": ["Alibaba"]}

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

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
REPLICATE_POLL_TIMEOUT_SECONDS = int(os.getenv("REPLICATE_POLL_TIMEOUT_SECONDS", "900"))
REPLICATE_POLL_INTERVAL_SECONDS = float(os.getenv("REPLICATE_POLL_INTERVAL_SECONDS", "3"))

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY") or os.getenv("RUNPOD_KEY")

RUNPOD_MANHWA_ENDPOINT_ID = os.getenv("RUNPOD_MANHWA_ENDPOINT_ID")
RUNPOD_MANHWA_TIMEOUT_SECONDS = int(os.getenv("RUNPOD_MANHWA_TIMEOUT_SECONDS", "900"))
RUNPOD_MANHWA_POLL_INTERVAL_SECONDS = float(os.getenv("RUNPOD_MANHWA_POLL_INTERVAL_SECONDS", "3"))
RUNPOD_MANHWA_QUEUE_TIMEOUT_SECONDS = int(os.getenv("RUNPOD_MANHWA_QUEUE_TIMEOUT_SECONDS", "180"))
RUNPOD_MANHWA_EXECUTION_TIMEOUT_MS = int(os.getenv("RUNPOD_MANHWA_EXECUTION_TIMEOUT_MS", "900000"))
RUNPOD_MANHWA_TTL_MS = int(os.getenv("RUNPOD_MANHWA_TTL_MS", "1200000"))

RUNPOD_FACE_SWAP_ENDPOINT_ID = (
    os.getenv("RUNPOD_FACE_SWAP_ENDPOINT_ID")
    or os.getenv("RUNPOD_FACEFUSION_ENDPOINT_ID")
)
RUNPOD_FACE_SWAP_TIMEOUT_SECONDS = int(os.getenv("RUNPOD_FACE_SWAP_TIMEOUT_SECONDS", "330"))
RUNPOD_FACE_SWAP_POLL_INTERVAL_SECONDS = float(os.getenv("RUNPOD_FACE_SWAP_POLL_INTERVAL_SECONDS", "3"))
RUNPOD_FACE_SWAP_EXECUTION_TIMEOUT_MS = int(os.getenv("RUNPOD_FACE_SWAP_EXECUTION_TIMEOUT_MS", "300000"))
RUNPOD_FACE_SWAP_TTL_MS = int(os.getenv("RUNPOD_FACE_SWAP_TTL_MS", "600000"))
RUNPOD_FACE_SWAP_PRESET = os.getenv("RUNPOD_FACE_SWAP_PRESET", "hyperswap_1a_512")
RUNPOD_FACE_SWAP_OUTPUT_FORMAT = os.getenv("RUNPOD_FACE_SWAP_OUTPUT_FORMAT", "png")

ADMIN_TELEGRAM_IDS = [int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()]

PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET")
PLATEGA_BASE_URL = os.getenv("PLATEGA_BASE_URL", "https://app.platega.io/").rstrip("/") + "/"
