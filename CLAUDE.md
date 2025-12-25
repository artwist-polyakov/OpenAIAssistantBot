# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Проект

Telegram бот с интеграцией OpenAI Assistants API. Каждый пользователь получает свой thread для контекста диалога. Работает через polling (не webhooks).

## Технологический стек

- Python 3.10+
- python-telegram-bot 21.x (async)
- OpenAI Assistants API
- Sentry для мониторинга ошибок
- Docker/Docker Compose

## Команды разработки

```bash
# Сборка и запуск
docker compose up -d --build

# Просмотр логов
docker compose logs -f

# Остановка
docker compose down

# Проверка синтаксиса
python3 -m py_compile src/bot.py

# Линтинг (если установлен)
flake8 src/
isort --check-only src/
```

## Архитектура

### Структура слоёв

- **src/bot.py** — основная логика: обработка сообщений, управление тредами, контроль доступа
- **src/chat_manager.py** — персистентность информации о чатах в `data/chat_list.json`
- **docker-compose.yml** — оркестрация с healthcheck

### Поток обработки сообщения

1. Сообщение → `handle_message()`
2. `should_bot_respond()` — проверка банов, разрешённых чатов, упоминания бота
3. Контроль доступа: rate limiting, валидация длины, whitelist пользователей
4. Получение/создание OpenAI thread (хранится в `user_threads` dict)
5. Отправка в OpenAI Assistants API → ожидание с таймаутом
6. Очистка ответа от chunk-маркеров → ответ пользователю

### Управление тредами

- Треды в памяти с heap-структурой для эффективной очистки
- Старые треды удаляются после `THREAD_LIFETIME_HOURS` (по умолчанию 24ч)
- File lock (`/app/data/bot.lock`) предотвращает запуск нескольких инстансов

### Отказоустойчивость

- **Graceful shutdown** — обработчики SIGTERM/SIGINT сохраняют данные перед выходом
- **Rate limiting** — ограничение сообщений на пользователя в единицу времени
- **Таймаут ассистента** — отмена run при превышении лимита ожидания
- **Проверка статуса run** — обработка failed/cancelled/expired

### Контроль доступа

- `USERS` — whitelist usernames (или `*` для всех)
- `ALLOWED_CHATS` — whitelist ID чатов (или `*`)
- `BANNED_USERS` / `BANNED_CHATS` — blocklist с причинами

## Стиль кода

- Max line length: 99
- Max complexity: 10
- Flake8 ignores: W503, F811, E203

## Переменные окружения

Обязательные: `BOT_TOKEN`, `OPENAI_API_KEY`, `ASSISTANT_ID`

Лимиты: `MAX_MESSAGE_LENGTH`, `ASSISTANT_TIMEOUT`, `RATE_LIMIT_MESSAGES`, `RATE_LIMIT_WINDOW`

Sentry: `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE`

## Важные ограничения

- **Не читать и не писать `.env` файлы напрямую**
- Данные персистятся в: `data/chat_list.json`, `logs/bot.log`
