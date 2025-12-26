"""Telegram бот с интеграцией OpenAI Assistants API."""
import logging
import signal
import sys

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                          ContextTypes, JobQueue, MessageHandler, filters)

from access_control import acquire_lock, release_lock, set_bot_info
from config import (BOT_TOKEN, SENTRY_DSN, SENTRY_ENVIRONMENT,
                    SENTRY_PROFILES_SAMPLE_RATE, SENTRY_TRACES_SAMPLE_RATE)
from handlers import chat_manager, get_chat_info, handle_message, reset_thread
from thread_manager import cleanup_old_threads, delete_all_threads
from utils import setup_logging

# Настройка логирования
setup_logging()


def sentry_before_send(event, hint):
    """Фильтрация временных сетевых ошибок из Sentry."""
    if "exc_info" in hint:
        exc_type = hint["exc_info"][0]
        if exc_type and "NetworkError" in exc_type.__name__:
            return None
    return event


# Инициализация Sentry
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=SENTRY_PROFILES_SAMPLE_RATE,
        integrations=[
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
        environment=SENTRY_ENVIRONMENT,
        before_send=sentry_before_send,
    )
    logging.info("Sentry monitoring initialized")


async def init_bot(application: Application):
    """Инициализация бота и получение информации о нем."""
    bot_info = await application.bot.get_me()
    set_bot_info(bot_info)
    logging.info(f"Bot initialized: @{bot_info.username}")


async def startup(application: Application):
    """Действия при запуске бота."""
    await init_bot(application)
    logging.info("Очистка всех тредов при запуске...")
    await delete_all_threads()


def graceful_shutdown(signum, frame):
    """Обработчик сигналов для graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logging.info(f"Received signal {sig_name}, initiating graceful shutdown...")

    try:
        chat_manager._save_chats()
        logging.info("Chat data saved successfully")
    except Exception as e:
        logging.error(f"Error saving chat data: {e}")

    release_lock()
    logging.info("Graceful shutdown completed")
    sys.exit(0)


def main():
    """Точка входа в приложение."""
    # Получаем блокировку
    acquire_lock()

    # Устанавливаем обработчики сигналов
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    try:
        application = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            .job_queue(JobQueue())
            .post_init(startup)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .build()
        )

        # Регистрация обработчиков
        application.add_handler(CommandHandler("chatinfo", get_chat_info))
        application.add_handler(CommandHandler("reset", reset_thread))
        application.add_handler(
            MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        )

        # Фоновая задача очистки тредов
        async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
            await cleanup_old_threads()

        application.job_queue.run_repeating(cleanup_job, interval=3600)

        # Запуск бота
        application.run_polling()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
