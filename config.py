import os
from dotenv import load_dotenv
from logging.config import dictConfig
from pathlib import Path

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required, set it in .env file")

# 确保日志目录存在
Path("logs").mkdir(parents=True, exist_ok=True)
dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            # ── 按业务域分文件 ──
            "file_app": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": "default",
                "filename": "logs/app.log",
                "maxBytes": 10 * 1024 * 1024,  # 10MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
            "file_agent": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": "default",
                "filename": "logs/agent.log",
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
            "file_chat": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": "default",
                "filename": "logs/chat.log",
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            # ── 第三方库噪音抑制 ──
            "httpx": {"level": "WARNING", "handlers": []},
            "openai": {"level": "WARNING", "handlers": []},
            "aiosqlite": {"level": "WARNING", "handlers": []},
            "aiosqlite.context": {"level": "WARNING", "handlers": []},
            "langchain_core": {"level": "WARNING", "handlers": []},
            # ── 业务日志（子 logger 通过 propagate=True 继承 pi_server 的 console+app）──
            "pi_server": {
                "level": "INFO",
                "handlers": ["console", "file_app"],
                "propagate": False,
            },
            "pi_server.agent": {
                "level": "INFO",
                "handlers": ["file_agent"],
                "propagate": True,  # 消息同时进入 file_agent + 父级 pi_server 的 console+app
            },
            "pi_server.chat": {
                "level": "INFO",
                "handlers": ["file_chat"],
                "propagate": True,
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
    }
)
