import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
