import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required, set it in .env file")
