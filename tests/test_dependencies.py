"""Регрессия: уязвимые версии зависимостей не должны ставиться."""
from importlib.metadata import version


def test_python_dotenv_patched_for_cve_2026_28684():
    parts = tuple(int(p) for p in version("python-dotenv").split(".")[:3])
    assert parts >= (1, 2, 2)
