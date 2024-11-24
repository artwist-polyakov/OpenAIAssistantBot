import os
import asyncio
import logging
import heapq
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update, Message
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
    JobQueue,
    Application,
)
import json
from pathlib import Path
from chat_manager import ChatManager

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
USERS = os.getenv("USERS", "*")
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS", "*")
THREAD_LIFETIME_HOURS = int(os.getenv("THREAD_LIFETIME_HOURS", "24"))

# Загрузка списков банов
BANNED_USERS = {}
BANNED_CHATS = {}

# Парсинг BANNED_USERS
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

# Парсинг BANNED_CHATS
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

# Парсинг остальных переменных
if USERS != "*":
    USERS = [user.strip() for user in USERS.split(",")]
if ALLOWED_CHATS != "*":
    ALLOWED_CHATS = [int(chat_id.strip()) for chat_id in ALLOWED_CHATS.split(",")]

# В начале файла добавим глобальную переменную
bot_info = None

# После загрузки переменных окружения
chat_manager = ChatManager()


@dataclass
class ThreadInfo:
    thread_id: str
    last_access: datetime
    user_id: int

    def __lt__(self, other):
        return self.last_access < other.last_access


# Структуры данных для хранения информации о тредах
thread_heap = []  # heap для быстрого доступа к старым тредам
user_threads: Dict[int, ThreadInfo] = {}  # словарь для быстрого доступа по user_id


async def cleanup_old_threads():
    """Очистка старых тредов"""
    while True:
        try:
            current_time = datetime.now()

            while thread_heap and current_time - thread_heap[0].last_access > timedelta(
                hours=THREAD_LIFETIME_HOURS
            ):
                oldest_thread = heapq.heappop(thread_heap)
                try:
                    # Удаляем тред в OpenAI
                    await client.beta.threads.delete(oldest_thread.thread_id)
                    # Удаляем из словаря пользователей
                    if oldest_thread.user_id in user_threads:
                        del user_threads[oldest_thread.user_id]
                    logging.info(
                        f"Deleted thread {oldest_thread.thread_id} "
                        f"for user {oldest_thread.user_id} due to inactivity"
                    )
                except Exception as e:
                    logging.error(f"Error deleting thread: {e}")
                    # Если произошла ошибка, возвращаем элемент обратно в кучу
                    heapq.heappush(thread_heap, oldest_thread)
                    break

        except Exception as e:
            logging.error(f"Error in cleanup process: {e}")

        await asyncio.sleep(3600)


async def update_thread_access(user_id: int, thread_id: str):
    """Обновление времени последнего доступа к треду"""
    current_time = datetime.now()

    # Создаем новый ThreadInfo
    thread_info = ThreadInfo(
        thread_id=thread_id, last_access=current_time, user_id=user_id
    )

    # Обновляем в словаре пользователей
    user_threads[user_id] = thread_info

    # Добавляем в кучу
    heapq.heappush(thread_heap, thread_info)


async def check_thread_exists(thread_id):
    try:
        await client.beta.threads.messages.list(thread_id=thread_id)
        return True
    except Exception as e:
        logging.warning(f"Thread {thread_id} not found: {e}")
        return False


async def should_bot_respond(
    message: Message, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверяем бан пользователя
    if user_id in BANNED_USERS:
        await message.reply_text(
            f"⛔️ Вы заблокированы.\n\nПричина: {BANNED_USERS[user_id]}"
        )
        return False

    # Для личных чатов проверяем бан чата сразу
    if message.chat.type == ChatType.PRIVATE:
        if chat_id in BANNED_CHATS:
            await message.reply_text(
                f"⛔️ Этот чат заблокирован.\n\nПричина: {BANNED_CHATS[chat_id]}"
            )
            return False
        return True

    # Проверяем, разрешен ли этот чат
    if ALLOWED_CHATS != "*" and chat_id not in ALLOWED_CHATS:
        return False

    # Используем глобальную переменную bot_info
    global bot_info

    # Проверяем, является ли сообщение ответом на сообщение бота или есть упоминание
    is_reply_to_bot = (
        message.reply_to_message
        and message.reply_to_message.from_user.id == bot_info.id
    )
    is_mention = False

    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                username = message.text[entity.offset : entity.offset + entity.length]
                if username.lower() == f"@{bot_info.username.lower()}":
                    is_mention = True
                    break

    # Если это обращение к боту и чат забанен, показываем сообщение
    if (is_reply_to_bot or is_mention) and chat_id in BANNED_CHATS:
        await message.reply_text(
            f"⛔️ Этот чат заблокирован.\n\nПричина: {BANNED_CHATS[chat_id]}"
        )
        return False

    return is_reply_to_bot or is_mention


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # В начале функции добавим обновление информации о чате
    chat = update.effective_chat
    chat_manager.update_chat(
        chat_id=chat.id,
        chat_type=chat.type,
        name=(
            chat.title
            if chat.title
            else f"Private chat with {update.effective_user.username}"
        ),
    )

    # Проверяем, должен ли бот ответить на это сообщение
    if not await should_bot_respond(update.message, context):
        return

    user = update.effective_user
    username = user.username
    user_id = user.id

    if USERS != "*" and username not in USERS:
        await update.message.reply_text("У вас нет доступа к боту.")
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    # Поверяем существование треда или создаем новый
    thread_info = user_threads.get(user_id)
    if thread_info is None or not await check_thread_exists(thread_info.thread_id):
        thread = await client.beta.threads.create()
        await update_thread_access(user_id, thread.id)
        logging.info(f"Created new thread {thread.id} for user {user_id}")
        thread_id = thread.id
    else:
        thread_id = thread_info.thread_id
        # Обновляем время последнего обращения
        await update_thread_access(user_id, thread_id)

    # Добавляем сообщение в существующий Thread
    await client.beta.threads.messages.create(
        thread_id=thread_id, role="user", content=update.message.text
    )

    # Запускаем ассистента в существующем Thread
    run = await client.beta.threads.runs.create(
        thread_id=thread_id, assistant_id=ASSISTANT_ID
    )

    # Ожидание завершения работы ассистента
    while True:
        run = await client.beta.threads.runs.retrieve(
            thread_id=thread_id, run_id=run.id
        )
        if run.completed_at:
            break
        await asyncio.sleep(2)

    # Получение ответа от ассистента
    messages = await client.beta.threads.messages.list(thread_id=thread_id)
    response = messages.data[0].content[0].text.value

    # Отправка ответа пользователю
    await update.message.reply_text(response)


async def init_bot(application):
    """Инициализация бота и получение информации о нем"""
    global bot_info
    bot_info = await application.bot.get_me()
    logging.info(f"Bot initialized: @{bot_info.username}")


async def post_init(application: Application) -> None:
    """Пост-инициализация приложения"""
    await init_bot(application)


async def get_chat_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для получения информации о чате"""
    chat = update.effective_chat
    user = update.effective_user

    info_message = (
        f"📝 Информация о чате:\n"
        f"ID чата: {chat.id}\n"
        f"Тип чата: {chat.type}\n"
        f"Название: {chat.title if chat.title else 'Личный чат'}\n\n"
        f"👤 Информация о пользователе:\n"
        f"ID пользователя: {user.id}\n"
        f"Username: @{user.username if user.username else 'отсутствует'}"
    )

    await update.message.reply_text(info_message)


def main():
    # Включаем job_queue при создании приложения
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .post_init(post_init)  # Добавляем пост-инициализацию
        .build()
    )

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("chatinfo", get_chat_info))

    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    # Добавляем задачу очистки как job в application
    async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
        await cleanup_old_threads()

    application.job_queue.run_repeating(cleanup_job, interval=3600)

    # Запускаем бота
    application.run_polling()


if __name__ == "__main__":
    main()
