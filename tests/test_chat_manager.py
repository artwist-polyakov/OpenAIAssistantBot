"""Тесты ChatManager."""
from chat_manager import ChatManager


def test_creates_file_and_updates_chat(tmp_path):
    path = tmp_path / "chat_list.json"
    manager = ChatManager(file_path=str(path))

    assert path.exists()
    assert manager.get_all_chats() == {}

    manager.update_chat(42, "private", "Alice")
    info = manager.get_chat_info(42)

    assert info is not None
    assert info.chat_id == 42
    assert info.chat_type == "private"
    assert info.name == "Alice"
    assert info.first_seen == info.last_message


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "chat_list.json"
    first = ChatManager(file_path=str(path))
    first.update_chat(7, "group", "Team")

    second = ChatManager(file_path=str(path))
    info = second.get_chat_info(7)

    assert info is not None
    assert info.name == "Team"
    assert info.chat_type == "group"


def test_update_existing_chat_keeps_first_seen(tmp_path):
    path = tmp_path / "chat_list.json"
    manager = ChatManager(file_path=str(path))
    manager.update_chat(1, "private", "Bob")
    first_seen = manager.get_chat_info(1).first_seen

    manager.update_chat(1, "private", "Bob")
    info = manager.get_chat_info(1)

    assert info.first_seen == first_seen
    assert info.last_message >= first_seen
