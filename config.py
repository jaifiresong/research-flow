import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-390ea1267e654c0fa3e3d271237e6696")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")
