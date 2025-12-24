"""Контроль доступа - file lock, rate limiting, проверка разрешений."""
import fcntl
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import Message
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from config import (ALLOWED_CHATS, BANNED_CHATS, BANNED_USERS, LOCK_FILE,
                    RATE_LIMIT_MESSAGES, RATE_LIMIT_WINDOW)

# File lock
lock_fd: Optional[int] = None

# Rate limiting - хранение времени последних сообщений пользователей
user_message_times: Dict[int, list] = defaultdict(list)

# Глобальная переменная для информации о боте (устанавливается при инициализации)
bot_info = None


def set_bot_info(info):
    """Устанавливает информацию о боте."""
    global bot_info
    bot_info = info


def acquire_lock():
    """Получает эксклюзивную блокировку для предотвращения множественных инстансов."""
    global lock_fd
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        logging.info(f"Lock acquired, PID: {os.getpid()}")
        return lock_fd
    except BlockingIOError:
        logging.error("Another bot instance is already running. Exiting.")
        sys.exit(1)


def release_lock():
    """Освобождает блокировку."""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            LOCK_FILE.unlink(missing_ok=True)
            logging.info("Lock released")
        except Exception as e:
            logging.error(f"Error releasing lock: {e}")


def check_rate_limit(user_id: int) -> bool:
    """Проверяет, не превышен ли лимит сообщений для пользователя.
    Возвращает True, если сообщение разрешено, False если превышен лимит."""
    now = datetime.now()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)

    # Очищаем старые записи
    user_message_times[user_id] = [
        t for t in user_message_times[user_id] if t > window_start
    ]

    # Проверяем лимит
    if len(user_message_times[user_id]) >= RATE_LIMIT_MESSAGES:
        return False

    # Добавляем текущее время
    user_message_times[user_id].append(now)
    return True


async def should_bot_respond(
    message: Message, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Проверяет, должен ли бот отвечать на это сообщение."""
    global bot_info

    if not message or not message.from_user:
        logging.warning("Получено сообщение без необходимых атрибутов")
        return False

    chat_id = message.chat_id if message.chat else None
    user_id = message.from_user.id if message.from_user else None

    if chat_id is None or user_id is None:
        logging.warning("Сообщение не содержит chat_id или user_id")
        return False

    # Проверяем бан пользователя
    if user_id in BANNED_USERS:
        try:
            await message.reply_text(
                f"⛔️ Вы заблокированы.\n\nПричина: {BANNED_USERS[user_id]}"
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения о бане: {e}")
        return False

    # Для личных чатов проверяем бан чата
    if message.chat and message.chat.type == ChatType.PRIVATE:
        if chat_id in BANNED_CHATS:
            try:
                await message.reply_text(
                    f"⛔️ Этот чат заблокирован.\n\nПричина: {BANNED_CHATS[chat_id]}"
                )
            except Exception as e:
                logging.error(f"Ошибка при отправке сообщения о бане чата: {e}")
            return False
        return True

    # Проверяем, разрешен ли этот чат
    if ALLOWED_CHATS != "*" and chat_id not in ALLOWED_CHATS:
        return False

    if not bot_info:
        logging.error("bot_info не инициализирован")
        return False

    # Проверяем, является ли сообщение ответом на сообщение бота или есть упоминание
    is_reply_to_bot = (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == bot_info.id
    )

    is_mention = False
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                username = message.text[entity.offset: entity.offset + entity.length]
                if username.lower() == f"@{bot_info.username.lower()}":
                    is_mention = True
                    break

    # Если это обращение к боту и чат забанен, показываем сообщение
    if (is_reply_to_bot or is_mention) and chat_id in BANNED_CHATS:
        try:
            await message.reply_text(
                f"⛔️ Этот чат заблокирован.\n\nПричина: {BANNED_CHATS[chat_id]}"
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения о бане чата: {e}")
        return False

    return is_reply_to_bot or is_mention
