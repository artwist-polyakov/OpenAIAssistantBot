"""Утилиты бота - логирование и очистка ответов."""
import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler

from config import REMOVE_CHUNK_MARKERS, REMOVE_CHUNKS_FOR_FILES


def setup_logging():
    """Настройка логирования с ежедневной ротацией."""
    log_dir = "/app/logs"
    log_file = os.path.join(log_dir, "bot.log")

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)


async def clean_assistant_response(response: str) -> str:
    """Очищает ответ ассистента от технических метаданных."""
    cleaned = response

    # Если в списке есть звездочка, удаляем все чанки
    if "*" in REMOVE_CHUNKS_FOR_FILES:
        cleaned = re.sub(r"【\d+:\d+†[^】]+】", "", cleaned)
        return cleaned.strip()

    # Иначе обрабатываем по файлам
    for filename in REMOVE_CHUNKS_FOR_FILES:
        filename = filename.strip()
        if filename:
            cleaned = re.sub(r"【\d+:\d+†" + re.escape(filename) + r"】", "", cleaned)

    if REMOVE_CHUNK_MARKERS:
        cleaned = re.sub(
            r"【\d+:\d+†([^】]+)】", lambda m: f" ({m.group(1)}) ", cleaned
        )

    # Исправляем множественные пробелы и переносы строк
    cleaned = re.sub(r" +", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)
    cleaned = re.sub(r" +\n", "\n", cleaned)
    cleaned = re.sub(r"\n +", "\n", cleaned)

    return cleaned.strip()
