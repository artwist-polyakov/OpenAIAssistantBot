"""Тесты очистки ответов ассистента."""
import pytest

import utils


@pytest.mark.asyncio
async def test_clean_removes_markers_for_listed_file(monkeypatch):
    monkeypatch.setattr(utils, "REMOVE_CHUNKS_FOR_FILES", ["links.txt"])
    monkeypatch.setattr(utils, "REMOVE_CHUNK_MARKERS", False)

    text = "См. 【1:2†links.txt】и ещё текст"
    result = await utils.clean_assistant_response(text)

    assert "【" not in result
    assert "links.txt" not in result
    assert "См." in result
    assert "и ещё текст" in result


@pytest.mark.asyncio
async def test_clean_removes_all_chunks_when_star(monkeypatch):
    monkeypatch.setattr(utils, "REMOVE_CHUNKS_FOR_FILES", ["*"])
    monkeypatch.setattr(utils, "REMOVE_CHUNK_MARKERS", True)

    text = "A【1:0†foo.md】B【2:3†bar.pdf】C"
    result = await utils.clean_assistant_response(text)

    assert result == "ABC"


@pytest.mark.asyncio
async def test_clean_replaces_other_markers_with_filename(monkeypatch):
    monkeypatch.setattr(utils, "REMOVE_CHUNKS_FOR_FILES", ["links.txt"])
    monkeypatch.setattr(utils, "REMOVE_CHUNK_MARKERS", True)

    text = "Источник【4:1†notes.md】здесь"
    result = await utils.clean_assistant_response(text)

    assert "【" not in result
    assert "(notes.md)" in result
    assert "Источник" in result
