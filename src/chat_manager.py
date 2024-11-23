import json
import logging
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChatInfo:
    chat_id: int
    chat_type: str
    name: str
    first_seen: str
    last_message: str


class ChatManager:
    def __init__(self, file_path: str = "data/chat_list.json"):
        self.file_path = Path(file_path)
        self.chats: Dict[int, ChatInfo] = {}
        self._ensure_file_exists()
        self._load_chats()

    def _ensure_file_exists(self):
        """Создает директорию и файл, если они не существуют"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text("{}")

    def _load_chats(self):
        """Загружает список чатов из файла"""
        try:
            data = json.loads(self.file_path.read_text())
            for chat_id_str, info in data.items():
                chat_id = int(chat_id_str)
                self.chats[chat_id] = ChatInfo(
                    chat_id=chat_id,
                    chat_type=info["type"],
                    name=info["name"],
                    first_seen=info["first_seen"],
                    last_message=info["last_message"],
                )
        except Exception as e:
            logging.error(f"Error loading chats: {e}")

    def _save_chats(self):
        """Сохраняет список чатов в файл"""
        try:
            data = {
                str(chat_id): {
                    "type": info.chat_type,
                    "name": info.name,
                    "first_seen": info.first_seen,
                    "last_message": info.last_message,
                }
                for chat_id, info in self.chats.items()
            }
            self.file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            logging.error(f"Error saving chats: {e}")

    def update_chat(self, chat_id: int, chat_type: str, name: str):
        """Обновляет информацию о чате или добавляет новый"""
        now = datetime.now().isoformat()
        if chat_id not in self.chats:
            self.chats[chat_id] = ChatInfo(
                chat_id=chat_id,
                chat_type=chat_type,
                name=name,
                first_seen=now,
                last_message=now,
            )
            logging.info(f"New chat discovered: {name} (ID: {chat_id})")
        else:
            self.chats[chat_id].last_message = now
        self._save_chats()

    def get_chat_info(self, chat_id: int) -> Optional[ChatInfo]:
        """Возвращает информацию о чате"""
        return self.chats.get(chat_id)

    def get_all_chats(self) -> Dict[int, ChatInfo]:
        """Возвращает словарь всех чатов"""
        return self.chats
