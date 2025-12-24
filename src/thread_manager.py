"""Управление тредами OpenAI Assistants API."""
import asyncio
import heapq
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, THREAD_LIFETIME_HOURS

# OpenAI клиент
client = AsyncOpenAI(api_key=OPENAI_API_KEY)


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
    """Удаляет все треды из локального хранилища."""
    try:
        for user_id, thread_info in list(user_threads.items()):
            try:
                await client.beta.threads.delete(thread_info.thread_id)
                logging.info(f"Удален тред {thread_info.thread_id}")
                del user_threads[user_id]
            except Exception as e:
                logging.error(f"Ошибка при удалении треда {thread_info.thread_id}: {e}")

        thread_heap.clear()

    except Exception as e:
        logging.error(f"Ошибка при очистке тредов: {e}")


async def cleanup_old_threads():
    """Очистка старых тредов (запускается как фоновая задача)."""
    while True:
        try:
            current_time = datetime.now()

            while thread_heap:
                oldest_thread = thread_heap[0]

                if current_time - oldest_thread.last_access <= timedelta(
                    hours=THREAD_LIFETIME_HOURS
                ):
                    break

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

                if oldest_thread.user_id in user_threads:
                    del user_threads[oldest_thread.user_id]

        except Exception as e:
            logging.error(f"Ошибка в процессе очистки: {e}")

        await asyncio.sleep(3600)


async def update_thread_access(user_id: int, thread_id: str):
    """Обновление времени последнего доступа к треду."""
    current_time = datetime.now()

    thread_info = ThreadInfo(
        thread_id=thread_id, last_access=current_time, user_id=user_id
    )

    user_threads[user_id] = thread_info
    heapq.heappush(thread_heap, thread_info)


async def check_thread_exists(thread_id: str) -> bool:
    """Проверяет существование треда в OpenAI."""
    try:
        await client.beta.threads.messages.list(thread_id=thread_id)
        return True
    except Exception as e:
        logging.warning(f"Thread {thread_id} not found: {e}")
        return False


async def get_or_create_thread(user_id: int) -> str:
    """Получает существующий или создает новый тред для пользователя."""
    thread_info = user_threads.get(user_id)

    if thread_info is None or not await check_thread_exists(thread_info.thread_id):
        thread = await client.beta.threads.create()
        await update_thread_access(user_id, thread.id)
        logging.info(f"Created new thread {thread.id} for user {user_id}")
        return thread.id
    else:
        await update_thread_access(user_id, thread_info.thread_id)
        return thread_info.thread_id


async def delete_user_thread(user_id: int) -> bool:
    """Удаляет тред пользователя. Возвращает True если тред существовал."""
    thread_info = user_threads.get(user_id)

    if not thread_info:
        return False

    try:
        await client.beta.threads.delete(thread_info.thread_id)
        logging.info(f"Удален тред {thread_info.thread_id} для пользователя {user_id}")
    except Exception as e:
        error_message = str(e).lower()
        if "404" in error_message and "no thread found" in error_message:
            logging.info(f"Тред {thread_info.thread_id} уже удален")
        else:
            logging.error(f"Ошибка при удалении треда: {e}")

    if user_id in user_threads:
        del user_threads[user_id]

    return True
