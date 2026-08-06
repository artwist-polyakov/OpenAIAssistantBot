"""Общие фикстуры: env до импорта модулей проекта."""
import os

# config.py читает env при импорте — задаём заглушки заранее
os.environ.setdefault("BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ASSISTANT_ID", "test-assistant-id")
