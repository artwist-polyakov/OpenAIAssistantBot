"""Обработка citations и annotations из OpenAI Assistants API."""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from config import (
    CITATIONS_MAX_QUOTE_LENGTH,
    CITATIONS_SHOW_QUOTES,
    ENABLE_CITATIONS,
    FILE_CACHE_TTL_HOURS,
)
from thread_manager import client

# Кэш метаданных файлов: file_id -> (filename, cached_at)
_file_cache: Dict[str, Tuple[str, datetime]] = {}


@dataclass
class Citation:
    """Информация о цитате/источнике."""
    index: int              # Порядковый номер [1], [2]...
    file_id: str            # OpenAI file ID
    filename: str           # Имя файла (из кэша)
    quote: Optional[str]    # Цитата (может быть None)
    marker_text: str        # Оригинальный маркер
    start_index: int        # Позиция в тексте
    end_index: int          # Конец маркера


@dataclass
class ProcessedResponse:
    """Обработанный ответ с citations."""
    text: str               # Текст с [1], [2] вместо маркеров
    citations: List[Citation]
    footnotes: str          # Готовые сноски


async def get_cached_filename(file_id: str) -> str:
    """Получает имя файла с кэшированием."""
    if file_id in _file_cache:
        filename, cached_at = _file_cache[file_id]
        if datetime.now() - cached_at < timedelta(hours=FILE_CACHE_TTL_HOURS):
            return filename

    try:
        file_info = await client.files.retrieve(file_id)
        filename = file_info.filename
        _file_cache[file_id] = (filename, datetime.now())
        return filename
    except Exception as e:
        logging.warning(f"Failed to retrieve file {file_id}: {e}")
        return f"источник_{file_id[:8]}"


async def resolve_filenames(file_ids: Set[str]) -> Dict[str, str]:
    """Получает имена файлов для набора file_id."""
    result = {}
    for file_id in file_ids:
        result[file_id] = await get_cached_filename(file_id)
    return result


def escape_markdown_v2(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    result = []
    for char in text:
        if char in special_chars:
            result.append('\\')
        result.append(char)
    return ''.join(result)


def truncate_quote(quote: str, max_length: int) -> str:
    """Обрезает цитату до максимальной длины."""
    if len(quote) <= max_length:
        return quote
    return quote[:max_length - 3] + "..."


def format_footnotes(citations: List[Citation]) -> str:
    """Форматирует сноски с курсивными цитатами для MarkdownV2."""
    if not citations:
        return ""

    lines = ["", "\\-\\-\\-", "*Источники:*"]

    for c in citations:
        filename_escaped = escape_markdown_v2(c.filename)
        line = f"\\[{c.index}\\]: {filename_escaped}"

        if CITATIONS_SHOW_QUOTES and c.quote:
            truncated = truncate_quote(c.quote, CITATIONS_MAX_QUOTE_LENGTH)
            quote_escaped = escape_markdown_v2(truncated)
            line += f" — _\"{quote_escaped}\"_"

        lines.append(line)

    return "\n".join(lines)


async def process_response_with_citations(content_block) -> ProcessedResponse:
    """Обрабатывает ответ OpenAI с извлечением citations."""
    # Проверяем, включена ли обработка citations
    if not ENABLE_CITATIONS:
        from utils import clean_assistant_response
        cleaned = await clean_assistant_response(content_block.text.value)
        return ProcessedResponse(text=cleaned, citations=[], footnotes="")

    text = content_block.text.value
    annotations = getattr(content_block.text, 'annotations', None) or []

    # Если нет annotations - fallback к старой логике
    if not annotations:
        from utils import clean_assistant_response
        cleaned = await clean_assistant_response(text)
        return ProcessedResponse(text=cleaned, citations=[], footnotes="")

    # Собираем уникальные file_id
    file_ids: Set[str] = set()
    for ann in annotations:
        if ann.type == "file_citation":
            file_citation = getattr(ann, 'file_citation', None)
            if file_citation:
                file_ids.add(file_citation.file_id)

    # Получаем имена файлов
    filenames = await resolve_filenames(file_ids)

    # Создаём citations
    citations: List[Citation] = []
    for i, ann in enumerate(annotations, 1):
        if ann.type == "file_citation":
            file_citation = getattr(ann, 'file_citation', None)
            if file_citation:
                file_id = file_citation.file_id
                quote = getattr(file_citation, 'quote', None)

                citations.append(Citation(
                    index=i,
                    file_id=file_id,
                    filename=filenames.get(file_id, "unknown"),
                    quote=quote,
                    marker_text=ann.text,
                    start_index=ann.start_index,
                    end_index=ann.end_index
                ))

    # Если citations пусты после фильтрации - fallback
    if not citations:
        from utils import clean_assistant_response
        cleaned = await clean_assistant_response(text)
        return ProcessedResponse(text=cleaned, citations=[], footnotes="")

    # Заменяем маркеры на номера сносок [1], [2]...
    # Важно: заменять с конца, чтобы не сбить индексы
    processed_text = text
    for citation in sorted(citations, key=lambda c: c.start_index, reverse=True):
        processed_text = (
            processed_text[:citation.start_index] +
            f"[{citation.index}]" +
            processed_text[citation.end_index:]
        )

    # Формируем сноски
    footnotes = format_footnotes(citations)

    # Экранируем основной текст для MarkdownV2
    escaped_text = escape_markdown_v2(processed_text)

    return ProcessedResponse(
        text=escaped_text,
        citations=citations,
        footnotes=footnotes
    )
