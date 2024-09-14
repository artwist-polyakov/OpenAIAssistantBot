import os
import asyncio
import logging
from dotenv import load_dotenv, set_key
from openai import AsyncOpenAI
from telegram import Update
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
HISTORY_DEPTH = int(os.getenv('HISTORY_DEPTH', '5'))

# Словарь для хранения истории пользователей
user_histories = {}

async def process_query(messages):
    assistant_id = ASSISTANT_ID

    # Создание нового потока
    thread = await client.beta.threads.create()
    thread_id = thread.id
    logging.info(f"Thread ID: {thread_id}")

    # Отправка сообщений в поток
    for message in messages:
        role = message['role']
        content = message['content']
        msg = await client.beta.threads.messages.create(
            thread_id=thread_id,
            role=role,
            content=content,
        )
        logging.info(f"Message created: {msg}")

    # Запуск ассистента
    run = await client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
    logging.info(f"Initial run: {run}")

    # Ожидание завершения работы ассистента
    while not run.completed_at:
        logging.info(f"Run status: {run.status}, waiting for completion...")
        await asyncio.sleep(2)
        run = await client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

    logging.info(f"Run completed: {run}")

    # Получение ответа от ассистента
    thread_messages = await client.beta.threads.messages.list(thread_id)
    # Ответ ассистента обычно является последним сообщением
    if thread_messages.data:
        for msg in reversed(thread_messages.data):
            if msg.role == 'assistant':
                return msg.content[0].text.value

    return "No response from assistant"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username
    user_id = user.id

    # Проверка доступа пользователя
    if USERS != '*' and username not in USERS:
        await update.message.reply_text('У вас нет доступа к боту.')
        return

    # Получение истории пользователя
    history = user_histories.get(user_id, [])

    # Подготовка сообщений для ассистента
    messages = []
    if update.message.reply_to_message and history:
        # Включаем предысторию в сообщения
        for q, a in history:
            messages.append({'role': 'user', 'content': q})
            messages.append({'role': 'assistant', 'content': a})
    # Добавляем новое сообщение пользователя
    messages.append({'role': 'user', 'content': update.message.text})

    # Получение ответа от ассистента
    response = await process_query(messages)

    # Отправка ответа пользователю
    await update.message.reply_text(response)

    # Обновление истории пользователя
    history.append((update.message.text, response))
    # Удаляем лишние записи из истории
    user_histories[user_id] = history[-HISTORY_DEPTH:]

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    application.run_polling()

if __name__ == '__main__':
    main()