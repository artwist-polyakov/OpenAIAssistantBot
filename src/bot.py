import asyncio
import heapq
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

import sentry_sdk
from dotenv import load_dotenv
from openai import AsyncOpenAI
from sentry_sdk.integrations.logging import LoggingIntegration
from telegram import Message, Update
from telegram.constants import ChatAction, ChatType
from telegram.error import Forbidden
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
    MessageHandler,
    filters,
)

from chat_manager import ChatManager

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Настройка логирования
def setup_logging():
    """Настройка логирования с ежедневной ротацией"""
    # Используем абсолютный путь в контейнере
    log_dir = "/app/logs"
    log_file = os.path.join(log_dir, "bot.log")

    # Настраиваем форматирование
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Создаем handler с ротацией
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",  # Ротация каждую полночь
        interval=1,  # Интервал - 1 день
        backupCount=7,  # Хранить логи за последние 7 дней
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)


setup_logging()

# Загрузка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
USERS = os.getenv("USERS", "*")
ALLOWED_CHATS = os.getenv("ALLOWED_CHATS", "*")
THREAD_LIFETIME_HOURS = int(os.getenv("THREAD_LIFETIME_HOURS", "24"))
REMOVE_CHUNKS_FOR_FILES = os.getenv("REMOVE_CHUNKS_FOR_FILES", "links.txt").split(",")
REMOVE_CHUNK_MARKERS = os.getenv("REMOVE_CHUNK_MARKERS", "true").lower() == "true"

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

# Инициализация Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        integrations=[
            LoggingIntegration(
                level=logging.INFO,  # Capture INFO and above as breadcrumbs
                event_level=logging.ERROR,  # Send errors as events
            ),
        ],
    )
    logging.info("Sentry monitoring initialized")


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


async def delete_all_threads():
    """Удаляет треды из локального хранилища"""
    try:
        # Очищаем локальные треды
        for user_id, thread_info in list(user_threads.items()):
            try:
                await client.beta.threads.delete(thread_info.thread_id)
                logging.info(f"Удален тред {thread_info.thread_id}")
                del user_threads[user_id]
            except Exception as e:
                logging.error(f"Ошибка при удалении треда {thread_info.thread_id}: {e}")

        # Очищаем heap
        thread_heap.clear()

    except Exception as e:
        logging.error(f"Ошибка при очистке тредов: {e}")


async def reset_thread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает тред пользователя"""
    try:
        user_id = update.effective_user.id
        thread_info = user_threads.get(user_id)

        if thread_info:
            # Удаляем старый тред
            try:
                await client.beta.threads.delete(thread_info.thread_id)
                logging.info(
                    f"Удален тред {thread_info.thread_id} для пользователя {user_id}"
                )
            except Exception as e:
                # Проверяем, является ли ошибка 404 "No thread found"
                error_message = str(e).lower()
                if "404" in error_message and "No thread found" in error_message:
                    logging.info(
                        f"Тред {thread_info.thread_id} уже удален, очищаем из локального хранилища"
                    )
                else:
                    logging.error(f"Ошибка при удалении треда: {e}")

            # В любом случае удаляем информацию о треде из структур данных
            if user_id in user_threads:
                del user_threads[user_id]

            await update.message.reply_text("✅ История диалога очищена.")
        else:
            await update.message.reply_text("ℹ️ У вас нет активного диалога.")

    except Exception as e:
        logging.error(f"Ошибка в reset_thread: {e}")
        await update.message.reply_text("❌ Произошла ошибка при сбросе диалога.")


async def startup(application: Application):
    """Действия при запуске бота"""
    await init_bot(application)
    logging.info("Очистка всех тредов при запуске...")
    await delete_all_threads()


async def cleanup_old_threads():
    """Очистка старых тредов"""
    while True:
        try:
            current_time = datetime.now()

            while thread_heap:
                # Смотрим на самый старый тред (но пока не удаляем его из кучи)
                oldest_thread = thread_heap[0]

                # Если тред еще не устарел, прерываем обработку
                if current_time - oldest_thread.last_access <= timedelta(
                    hours=THREAD_LIFETIME_HOURS
                ):
                    break

                # Удаляем тред из кучи
                oldest_thread = heapq.heappop(thread_heap)

                try:
                    await client.beta.threads.delete(oldest_thread.thread_id)
                    logging.info(
                        f"Удален устаревший тред {oldest_thread.thread_id} "
                        f"пользователя {oldest_thread.user_id}"
                    )
                except Exception as e:
                    error_message = str(e)
                    if "404" in error_message and "No thread found" in error_message:
                        logging.info(f"Тред {oldest_thread.thread_id} уже удален")
                    else:
                        logging.error(
                            f"Ошибка при удалении треда {oldest_thread.thread_id}: {e}"
                        )

                # В любом случае удаляем из словаря пользователей
                if oldest_thread.user_id in user_threads:
                    del user_threads[oldest_thread.user_id]

        except Exception as e:
            logging.error(f"Ошибка в процессе очистки: {e}")

        await asyncio.sleep(3600)  # Проверяем раз в час


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
    # Проверяем, что сообщение существует и содержит необходимые атрибуты
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

    # Используем глобальную переменную bot_info
    global bot_info
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
                username = message.text[entity.offset : entity.offset + entity.length]
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


async def clean_assistant_response(response: str) -> str:
    """Очищает ответ ассистента от технических метаданных"""
    cleaned = response

    # Если в списке есть звездочка, удаляем все чанки
    if "*" in REMOVE_CHUNKS_FOR_FILES:
        cleaned = re.sub(r"【\d+:\d+†[^】]+】", "", cleaned)
        return cleaned.strip()

    # Иначе обрабатываем по файлам
    for filename in REMOVE_CHUNKS_FOR_FILES:
        filename = filename.strip()
        if filename:
            # Полностью удаляем чанки для указанных файлов
            cleaned = re.sub(r"【\d+:\d+†" + re.escape(filename) + r"】", "", cleaned)

    if REMOVE_CHUNK_MARKERS:
        # Заменяем маркеры на пробел + имя файла + пробел
        cleaned = re.sub(
            r"【\d+:\d+†([^】]+)】", lambda m: f" ({m.group(1)}) ", cleaned
        )

    # Исправляем множественные пробелы и переносы строк
    cleaned = re.sub(r" +", " ", cleaned)  # Множественные пробелы
    cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)  # Множественные переносы
    cleaned = re.sub(r" +\n", "\n", cleaned)  # Пробелы перед переносом
    cleaned = re.sub(r"\n +", "\n", cleaned)  # Пробелы после переноса

    return cleaned.strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.effective_chat or not update.effective_user or not update.message:
            logging.warning("Получено обновление без необходимых атрибутов")
            return

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

        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
        except Forbidden:
            logging.warning(f"User {update.effective_chat.id} blocked the bot")
            return

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

        # Очищаем ответ перед отправкой
        cleaned_response = await clean_assistant_response(response)

        # Отправляем очищенный ответ пользователю
        await update.message.reply_text(cleaned_response)

    except Exception as e:
        logging.error(f"Error in handle_message: {e}")
        sentry_sdk.capture_exception(e)
        try:
            if update.message:
                await update.message.reply_text(
                    "Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте позже."
                )
        except Exception as reply_error:
            logging.error(f"Ошибка при отправке сообщения об ошибке: {reply_error}")


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
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .post_init(startup)  # Заменяем post_init на startup
        .build()
    )

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("chatinfo", get_chat_info))
    application.add_handler(
        CommandHandler("reset", reset_thread)
    )  # Добавляем команду reset

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
