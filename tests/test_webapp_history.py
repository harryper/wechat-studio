from webapp import history


def test_add_and_get_use_d1(memory_d1):
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "幸存者偏差",
        "theme": "terracotta",
        "workdir": "/tmp/x",
        "image_mode": "real",
        "status": "draft",
    })
    entry = history.get(entry_id)
    assert entry["title"] == "幸存者偏差"
    assert entry["workdir"] == "/tmp/x"


def test_delete_archives_entry(memory_d1):
    entry_id = history.add({"topic_id": "kb-001", "title": "x"})
    assert history.delete(entry_id) is True
    assert history.get(entry_id)["status"] == "archived"
    assert history.list_entries() == []


def test_delete_unknown_returns_false(memory_d1):
    assert history.delete(999) is False


def test_update_keeps_identity(memory_d1):
    entry_id = history.add({"topic_id": "kb-001", "title": "old", "workdir": "/tmp/a"})
    updated = history.update(entry_id, {"title": "new", "id": 999, "article_id": "bad"})
    assert updated["id"] == entry_id
    assert updated["title"] == "new"
    assert updated["workdir"] == "/tmp/a"
