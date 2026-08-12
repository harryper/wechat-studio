# tests/test_webapp_history.py
import json
import pytest
from pathlib import Path

from webapp import history


@pytest.fixture
def tmp_history_file(tmp_path, monkeypatch):
    """Point history module at a temp file so tests don't touch the real one."""
    f = tmp_path / "history.json"
    monkeypatch.setattr(history, "_HISTORY_FILE", f)
    monkeypatch.setattr(history, "_DATA_DIR", tmp_path)
    history._entries.clear()
    history._next_id = 1
    yield f
    history._entries.clear()
    history._next_id = 1


def test_add_does_not_persist_html_field(tmp_history_file):
    eid = history.add({
        "topic_id": "kb-001",
        "title": "幸存者偏差",
        "theme": "terracotta",
        "workdir": "/tmp/x",
        "image_mode": "real",
        "html": "<huge base64 blob>",  # caller might still pass it; add() must drop it
    })
    raw = json.loads(tmp_history_file.read_text())
    entry = raw["entries"][0]
    assert entry["id"] == eid
    assert "html" not in entry, "history must not persist html (1.7MB bloat)"


def test_delete_returns_true_and_removes_entry(tmp_history_file):
    a = history.add({"topic_id": "kb-001", "title": "x", "workdir": "/tmp/a"})
    b = history.add({"topic_id": "kb-002", "title": "y", "workdir": "/tmp/b"})
    assert history.delete(a) is True
    raw = json.loads(tmp_history_file.read_text())
    ids = [e["id"] for e in raw["entries"]]
    assert ids == [b]


def test_delete_unknown_id_returns_false(tmp_history_file):
    history.add({"topic_id": "kb-001", "title": "x", "workdir": "/tmp/a"})
    assert history.delete(999) is False
    assert len(history.list_entries()) == 1


def test_delete_decrements_next_id_via_load(tmp_history_file):
    history.add({"topic_id": "kb-001", "title": "x", "workdir": "/tmp/a"})
    history.add({"topic_id": "kb-002", "title": "y", "workdir": "/tmp/b"})
    raw = json.loads(tmp_history_file.read_text())
    saved_next_id = raw["next_id"]
    history._entries.clear()
    history._next_id = 1
    history.delete(1)
    # reload should pick up the saved next_id so new adds don't collide
    raw2 = json.loads(tmp_history_file.read_text())
    assert raw2["next_id"] == saved_next_id
