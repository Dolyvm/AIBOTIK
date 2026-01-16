import os
from pathlib import Path

CONTENT_BASE_PATH = Path(os.getenv("CONTENT_PATH", "/app/content"))

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
