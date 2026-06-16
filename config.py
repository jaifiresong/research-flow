import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

AGENT_BROWSER_PATH = os.getenv("AGENT_BROWSER_PATH", "agent-browser")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
DEFAULT_MAX_PAGES = 20
DEFAULT_OUTPUT_DIR = "output"
