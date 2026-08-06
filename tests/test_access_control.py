"""Тесты rate limiting."""
import access_control


def test_rate_limit_allows_within_window(monkeypatch):
    monkeypatch.setattr(access_control, "RATE_LIMIT_MESSAGES", 3)
    monkeypatch.setattr(access_control, "RATE_LIMIT_WINDOW", 60)
    access_control.user_message_times.clear()

    assert access_control.check_rate_limit(100) is True
    assert access_control.check_rate_limit(100) is True
    assert access_control.check_rate_limit(100) is True


def test_rate_limit_blocks_when_exceeded(monkeypatch):
    monkeypatch.setattr(access_control, "RATE_LIMIT_MESSAGES", 2)
    monkeypatch.setattr(access_control, "RATE_LIMIT_WINDOW", 60)
    access_control.user_message_times.clear()

    assert access_control.check_rate_limit(200) is True
    assert access_control.check_rate_limit(200) is True
    assert access_control.check_rate_limit(200) is False


def test_rate_limit_is_per_user(monkeypatch):
    monkeypatch.setattr(access_control, "RATE_LIMIT_MESSAGES", 1)
    monkeypatch.setattr(access_control, "RATE_LIMIT_WINDOW", 60)
    access_control.user_message_times.clear()

    assert access_control.check_rate_limit(1) is True
    assert access_control.check_rate_limit(1) is False
    assert access_control.check_rate_limit(2) is True
