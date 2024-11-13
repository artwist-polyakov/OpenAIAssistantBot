import os
import asyncio
import logging
from dotenv import load_dotenv, set_key
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ASSISTANT_ID = os.getenv('ASSISTANT_ID')
USERS = os.getenv('USERS', '*')
if USERS != '*':
    USERS = [user.strip() for user in USERS.split(',')]

# Добавим словарь для хранения Thread ID пользователей
user_threads = {}

async def check_thread_exists(thread_id):
    try:
        # Пробуем получить сообщения треда для проверки его существования
        await client.beta.threads.messages.list(thread_id=thread_id)
        return True
    except Exception as e:
        logging.warning(f"Thread {thread_id} not found: {e}")
        return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username
    user_id = user.id

    # Проверка доступа пользователя
    if USERS != '*' and username not in USERS:
        await update.message.reply_text('У вас нет доступа к боту.')
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Проверяем существование треда или создаем новый
    thread_id = user_threads.get(user_id)
    if thread_id is None or not await check_thread_exists(thread_id):
        thread = await client.beta.threads.create()
        thread_id = thread.id
        user_threads[user_id] = thread_id
        logging.info(f"Created new thread {thread_id} for user {user_id}")
    
    # Добавляем сообщение в существующий Thread
    await client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=update.message.text
    )
    
    # Запускаем ассистента в существующем Thread
    run = await client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ASSISTANT_ID
    )

    # Ожидание завершения работы ассистента
    while True:
        run = await client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id
        )
        if run.completed_at:
            break
        await asyncio.sleep(2)

    # Получение ответа от ассистента
    messages = await client.beta.threads.messages.list(thread_id=thread_id)
    response = messages.data[0].content[0].text.value

    # Отправка ответа пользователю
    await update.message.reply_text(response)

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    application.run_polling()

if __name__ == '__main__':
    main()