"""Управление тредами OpenAI Assistants API."""
import asyncio
import heapq
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, THREAD_LIFETIME_HOURS

# OpenAI клиент
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Тип ключа: (chat_id, user_id)
ThreadKey = Tuple[int, int]


@dataclass
class ThreadInfo:
    thread_id: str
    last_access: datetime
    chat_id: int
    user_id: int

    def __lt__(self, other):
        return self.last_access < other.last_access

    @property
    def key(self) -> ThreadKey:
        return (self.chat_id, self.user_id)


# Структуры данных для хранения информации о тредах
thread_heap = []  # heap для быстрого доступа к старым тредам
chat_user_threads: Dict[ThreadKey, ThreadInfo] = {}  # ключ: (chat_id, user_id)


async def delete_all_threads():
    """Удаляет все треды из локального хранилища."""
    try:
        for key, thread_info in list(chat_user_threads.items()):
            try:
                await client.beta.threads.delete(thread_info.thread_id)
                logging.info(f"Удален тред {thread_info.thread_id}")
                del chat_user_threads[key]
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
                        f"(chat={oldest_thread.chat_id}, user={oldest_thread.user_id})"
                    )
                except Exception as e:
                    error_message = str(e)
                    if "404" in error_message and "No thread found" in error_message:
                        logging.info(f"Тред {oldest_thread.thread_id} уже удален")
                    else:
                        logging.error(
                            f"Ошибка при удалении треда {oldest_thread.thread_id}: {e}"
                        )

                key = oldest_thread.key
                if key in chat_user_threads:
                    del chat_user_threads[key]

        except Exception as e:
            logging.error(f"Ошибка в процессе очистки: {e}")

        await asyncio.sleep(3600)


async def update_thread_access(chat_id: int, user_id: int, thread_id: str):
    """Обновление времени последнего доступа к треду."""
    current_time = datetime.now()
    key = (chat_id, user_id)

    existing = chat_user_threads.get(key)
    if existing and existing.thread_id == thread_id:
        # Обновляем существующий ThreadInfo
        existing.last_access = current_time
        heapq.heapify(thread_heap)  # Пересортировка кучи O(n)
    else:
        # Создаём новый только если нет или другой thread_id
        thread_info = ThreadInfo(
            thread_id=thread_id,
            last_access=current_time,
            chat_id=chat_id,
            user_id=user_id
        )
        chat_user_threads[key] = thread_info
        heapq.heappush(thread_heap, thread_info)


async def check_thread_exists(thread_id: str) -> bool:
    """Проверяет существование треда в OpenAI."""
    try:
        await client.beta.threads.messages.list(thread_id=thread_id)
        return True
    except Exception as e:
        logging.warning(f"Thread {thread_id} not found: {e}")
        return False


async def get_or_create_thread(chat_id: int, user_id: int) -> str:
    """Получает существующий или создает новый тред для пользователя в чате."""
    key = (chat_id, user_id)
    thread_info = chat_user_threads.get(key)

    if thread_info is None or not await check_thread_exists(thread_info.thread_id):
        thread = await client.beta.threads.create()
        await update_thread_access(chat_id, user_id, thread.id)
        logging.info(
            f"Created new thread {thread.id} for chat={chat_id}, user={user_id}"
        )
        return thread.id
    else:
        await update_thread_access(chat_id, user_id, thread_info.thread_id)
        return thread_info.thread_id


async def delete_user_thread(chat_id: int, user_id: int) -> bool:
    """Удаляет тред пользователя в чате. Возвращает True если тред существовал."""
    key = (chat_id, user_id)
    thread_info = chat_user_threads.get(key)

    if not thread_info:
        return False

    try:
        await client.beta.threads.delete(thread_info.thread_id)
        logging.info(
            f"Удален тред {thread_info.thread_id} для chat={chat_id}, user={user_id}"
        )
    except Exception as e:
        error_message = str(e).lower()
        if "404" in error_message and "no thread found" in error_message:
            logging.info(f"Тред {thread_info.thread_id} уже удален")
        else:
            logging.error(f"Ошибка при удалении треда: {e}")

    if key in chat_user_threads:
        del chat_user_threads[key]

    return True
