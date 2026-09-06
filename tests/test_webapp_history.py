from pathlib import Path

import pytest

from webapp import history, local_store


def _make_workdir(tmp_path: Path, name: str = "work", markdown: str = "# 标题\n\n正文") -> Path:
    wd = tmp_path / name
    wd.mkdir(exist_ok=True)
    (wd / "article.md").write_text(markdown, encoding="utf-8")
    return wd


def test_add_and_get_persists_to_local_files(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "幸存者偏差",
        "theme": "terracotta",
        "workdir": str(workdir),
        "image_mode": "real",
        "status": "draft",
    })
    entry = history.get(entry_id)
    assert entry["title"] == "幸存者偏差"
    assert entry["workdir"] == str(workdir)
    assert entry["markdown"] == "# 标题\n\n正文"
    on_disk = (local_storage / "history.json").read_text(encoding="utf-8")
    assert "幸存者偏差" in on_disk


def test_history_survives_module_reload(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "幸存者偏差",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })

    import importlib
    importlib.reload(history)

    entry = history.get(entry_id)
    assert entry is not None
    assert entry["title"] == "幸存者偏差"


def test_delete_removes_entry_and_does_not_reuse_id(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path)
    first_id = history.add({"topic_id": "kb-001", "title": "first",
                             "theme": "terracotta", "workdir": str(workdir)})
    history.delete(first_id)
    next_id = history.add({"topic_id": "kb-001", "title": "second",
                           "theme": "terracotta", "workdir": str(workdir)})
    assert next_id == first_id + 1
    assert history.get(first_id) is None
    assert history.get(next_id)["title"] == "second"


def test_list_entries_excludes_markdown(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path, markdown="# 标题\n\n很长的正文 " * 200)
    history.add({
        "topic_id": "kb-001",
        "title": "长文",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })
    entries = history.list_entries()
    assert all("markdown" not in e for e in entries)


def test_get_returns_markdown_from_workdir(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path, markdown="# 详情\n\n## 摘要\n\n正文内容")
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "详情",
        "theme": "terracotta",
        "workdir": str(workdir),
    })
    entry = history.get(entry_id)
    assert entry["markdown"] == "# 详情\n\n## 摘要\n\n正文内容"


def test_update_keeps_identity_blocks_immutable(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({"topic_id": "kb-001", "title": "old",
                             "theme": "terracotta", "workdir": str(workdir)})
    updated = history.update(entry_id, {
        "title": "new",
        "id": 999,
        "created_at": "2000-01-01T00:00:00Z",
        "markdown": "should be dropped",
    })
    assert updated["id"] == entry_id
    assert updated["title"] == "new"
    assert "markdown" not in updated


def test_corrupted_history_file_raises_storage_error(local_storage):
    (local_storage / "history.json").write_text("{ broken json", encoding="utf-8")
    with pytest.raises(local_store.StorageError):
        history.list_entries()


def test_atomic_write_does_not_destroy_previous_file_on_failure(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({"topic_id": "kb-001", "title": "good",
                             "theme": "terracotta", "workdir": str(workdir)})

    history_file = local_storage / "history.json"
    good = history_file.read_text(encoding="utf-8")

    class BoomJson:
        def dumps(self, *args, **kwargs):
            raise OSError("disk full")

    import json as json_mod
    original = json_mod.dumps
    json_mod.dumps = BoomJson().dumps
    try:
        with pytest.raises(OSError):
            history.update(entry_id, {"title": "broken"})
    finally:
        json_mod.dumps = original

    assert history_file.read_text(encoding="utf-8") == good
    assert history.get(entry_id)["title"] == "good"


def test_update_preserves_id_under_concurrent_writers(local_storage, tmp_path):
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({"topic_id": "kb-001", "title": "race",
                             "theme": "terracotta", "workdir": str(workdir)})
    history.update(entry_id, {"title": "race-2"})
    history.update(entry_id, {"title": "race-3"})
    assert history.get(entry_id)["title"] == "race-3"
