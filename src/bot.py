import os
import asyncio
import logging
import heapq
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict
from dotenv import load_dotenv, set_key
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    JobQueue
)

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ASSISTANT_ID = os.getenv('ASSISTANT_ID')
USERS = os.getenv('USERS', '*')
THREAD_LIFETIME_HOURS = int(os.getenv('THREAD_LIFETIME_HOURS', '24'))
if USERS != '*':
    USERS = [user.strip() for user in USERS.split(',')]

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
            
            while thread_heap and current_time - thread_heap[0].last_access > timedelta(hours=THREAD_LIFETIME_HOURS):
                oldest_thread = heapq.heappop(thread_heap)
                try:
                    # Удаляем тред в OpenAI
                    await client.beta.threads.delete(oldest_thread.thread_id)
                    # Удаляем из словаря пользователей
                    if oldest_thread.user_id in user_threads:
                        del user_threads[oldest_thread.user_id]
                    logging.info(f"Deleted thread {oldest_thread.thread_id} for user {oldest_thread.user_id} due to inactivity")
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
    thread_info = ThreadInfo(thread_id=thread_id, last_access=current_time, user_id=user_id)
    
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username
    user_id = user.id

    if USERS != '*' and username not in USERS:
        await update.message.reply_text('У вас нет доступа к боту.')
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Проверяем существование треда или создаем новый
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
    # Включаем job_queue при создании приложения
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .build()
    )

    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    # Добавляем задачу очистки как job в application
    async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
        await cleanup_old_threads()

    application.job_queue.run_repeating(cleanup_job, interval=3600)

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()