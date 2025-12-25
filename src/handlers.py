"""Обработчики команд и сообщений Telegram."""
import asyncio
import logging
from datetime import datetime

import sentry_sdk
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from access_control import check_rate_limit, should_bot_respond
from chat_manager import ChatManager
from config import (ASSISTANT_ID, ASSISTANT_TIMEOUT, MAX_MESSAGE_LENGTH,
                    RATE_LIMIT_WINDOW, USERS)
from thread_manager import client, delete_user_thread, get_or_create_thread
from utils import clean_assistant_response

# Менеджер чатов
chat_manager = ChatManager()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик сообщений."""
    try:
        if not update.effective_chat or not update.effective_user or not update.message:
            logging.warning("Получено обновление без необходимых атрибутов")
            return

        # Обновление информации о чате
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

        # Проверка доступа пользователя
        if USERS != "*":
            if username is None or username not in USERS:
                await update.message.reply_text("У вас нет доступа к боту.")
                return

        # Rate limiting
        if not check_rate_limit(user_id):
            await update.message.reply_text(
                f"Слишком много сообщений. Подождите немного ({RATE_LIMIT_WINDOW} сек)."
            )
            return

        # Валидация длины сообщения
        message_text = update.message.text
        if not message_text:
            return

        if len(message_text) > MAX_MESSAGE_LENGTH:
            await update.message.reply_text(
                f"Сообщение слишком длинное. Максимум: {MAX_MESSAGE_LENGTH} символов."
            )
            return

        # Отправка "печатает..."
        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
        except Forbidden:
            logging.warning(f"User {update.effective_chat.id} blocked the bot")
            return

        # Получаем или создаём тред (уникальный для каждого чата + пользователя)
        chat_id = update.effective_chat.id
        thread_id = await get_or_create_thread(chat_id, user_id)

        # Отправка в OpenAI
        response = await process_with_assistant(thread_id, message_text)

        # Очищаем и отправляем ответ
        cleaned_response = await clean_assistant_response(response)
        await update.message.reply_text(cleaned_response)

    except Exception as e:
        logging.error(f"Error in handle_message: {type(e).__name__}: {str(e)[:200]}")
        sentry_sdk.capture_exception(e)
        try:
            if update.message:
                await update.message.reply_text(
                    "Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте позже."
                )
        except Exception as reply_error:
            logging.error(f"Ошибка при отправке сообщения об ошибке: {reply_error}")


async def process_with_assistant(thread_id: str, message_text: str) -> str:
    """Отправляет сообщение ассистенту и ожидает ответ."""
    # Добавляем сообщение в Thread
    await client.beta.threads.messages.create(
        thread_id=thread_id, role="user", content=message_text
    )

    # Запускаем ассистента
    run = await client.beta.threads.runs.create(
        thread_id=thread_id, assistant_id=ASSISTANT_ID
    )

    # Ожидание завершения с таймаутом
    start_time = datetime.now()
    while True:
        run = await client.beta.threads.runs.retrieve(
            thread_id=thread_id, run_id=run.id
        )

        if run.completed_at:
            break

        if run.status == "failed":
            error_msg = run.last_error.message if run.last_error else "Unknown error"
            raise Exception(f"Assistant run failed: {error_msg}")

        if run.status == "cancelled":
            raise Exception("Assistant run was cancelled")

        if run.status == "expired":
            raise Exception("Assistant run expired")

        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > ASSISTANT_TIMEOUT:
            try:
                await client.beta.threads.runs.cancel(
                    thread_id=thread_id, run_id=run.id
                )
            except Exception:
                pass
            raise TimeoutError(f"Assistant timeout after {ASSISTANT_TIMEOUT} seconds")

        await asyncio.sleep(2)

    # Получение ответа
    messages = await client.beta.threads.messages.list(thread_id=thread_id)
    return messages.data[0].content[0].text.value


async def reset_thread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /reset - сброс треда пользователя."""
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        if await delete_user_thread(chat_id, user_id):
            await update.message.reply_text("✅ История диалога очищена.")
        else:
            await update.message.reply_text("ℹ️ У вас нет активного диалога.")

    except Exception as e:
        logging.error(f"Ошибка в reset_thread: {e}")
        await update.message.reply_text("❌ Произошла ошибка при сбросе диалога.")


async def get_chat_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /chatinfo - информация о чате."""
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
