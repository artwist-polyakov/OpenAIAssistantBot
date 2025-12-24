"""Конфигурация бота - загрузка переменных окружения и настройки."""
import logging
import os
from pathlib import Path
from typing import Dict, List, Union

from dotenv import load_dotenv

load_dotenv()

# Основные настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# Настройки доступа
USERS: Union[str, List[str]] = os.getenv("USERS", "*")
ALLOWED_CHATS: Union[str, List[int]] = os.getenv("ALLOWED_CHATS", "*")

# Настройки тредов
THREAD_LIFETIME_HOURS = int(os.getenv("THREAD_LIFETIME_HOURS", "24"))

# Настройки очистки ответов
REMOVE_CHUNKS_FOR_FILES = os.getenv("REMOVE_CHUNKS_FOR_FILES", "links.txt").split(",")
REMOVE_CHUNK_MARKERS = os.getenv("REMOVE_CHUNK_MARKERS", "true").lower() == "true"

# Лимиты и таймауты
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "10000"))
ASSISTANT_TIMEOUT = int(os.getenv("ASSISTANT_TIMEOUT", "120"))
RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", "10"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# File lock
LOCK_FILE = Path("/app/data/bot.lock")

# Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN")
SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
SENTRY_PROFILES_SAMPLE_RATE = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))
SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "production")

# Парсинг списков банов
BANNED_USERS: Dict[int, str] = {}
BANNED_CHATS: Dict[int, str] = {}

banned_users_str = os.getenv("BANNED_USERS", "")
if banned_users_str:
    try:
        for ban_entry in banned_users_str.split(","):
            if ":" in ban_entry:
                user_id, reason = ban_entry.strip().split(":", 1)
                reason = reason.replace("\\n", "\n").strip()
                BANNED_USERS[int(user_id.strip())] = reason
    except Exception as e:
        logging.error(f"Error parsing BANNED_USERS: {e}")

banned_chats_str = os.getenv("BANNED_CHATS", "")
if banned_chats_str:
    try:
        for ban_entry in banned_chats_str.split(","):
            if ":" in ban_entry:
                chat_id, reason = ban_entry.strip().split(":", 1)
                reason = reason.replace("\\n", "\n").strip()
                BANNED_CHATS[int(chat_id.strip())] = reason
    except Exception as e:
        logging.error(f"Error parsing BANNED_CHATS: {e}")

# Парсинг списков пользователей и чатов
if USERS != "*":
    USERS = [user.strip() for user in USERS.split(",")]
if ALLOWED_CHATS != "*":
    ALLOWED_CHATS = [int(chat_id.strip()) for chat_id in ALLOWED_CHATS.split(",")]
