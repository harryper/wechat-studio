"""Tests for cascade delete, publish error display, and degraded storage."""

import json
from pathlib import Path

import pytest

from webapp import history, jobs


def _make_workdir(tmp_path, name="work", markdown="# 标题\n\n## 摘要\n\n正文"):
    wd = tmp_path / name
    wd.mkdir()
    (wd / "article.md").write_text(markdown, encoding="utf-8")
    return wd


def test_delete_history_cascades_to_jobs_and_workdir(web_client, tmp_path):
    client, _ = web_client
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "可删除",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })
    j1 = jobs.create("article", {"history_id": entry_id, "topic": {"id": "kb-001"}})
    j2 = jobs.create("images", {"history_id": entry_id, "topic": {"id": "kb-001"}})

    response = client.delete(f"/api/history/{entry_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["deleted"] == entry_id
    assert payload["deleted_jobs"] == 2
    assert history.get(entry_id) is None
    assert jobs.get(j1["id"]) is None
    assert jobs.get(j2["id"]) is None
    assert not workdir.exists()


def test_deleting_one_history_preserves_shared_custom_topic(web_client, tmp_path, local_storage):
    from webapp import topics

    client, _ = web_client
    shared_topic = topics.create_topic({
        "title": "共享选题",
        "category": "custom",
        "context": {"origin": "", "key_points": [], "caution": "no"},
    })

    workdir_a = _make_workdir(tmp_path, "a")
    workdir_b = _make_workdir(tmp_path, "b")
    entry_a = history.add({
        "topic_id": shared_topic["id"],
        "title": "文章 A",
        "theme": "terracotta",
        "workdir": str(workdir_a),
    })
    entry_b = history.add({
        "topic_id": shared_topic["id"],
        "title": "文章 B",
        "theme": "terracotta",
        "workdir": str(workdir_b),
    })
    j_a = jobs.create("article", {"history_id": entry_a, "topic": {"id": shared_topic["id"]}})

    response = client.delete(f"/api/history/{entry_a}")
    assert response.status_code == 200

    # Custom topic still exists, entry B still exists, entry B's jobs untouched.
    assert topics.get_topic(shared_topic["id"]) is not None
    assert history.get(entry_b) is not None
    assert history.get(entry_a) is None
    assert jobs.get(j_a["id"]) is None


def test_deleting_history_is_idempotent(web_client, tmp_path):
    client, _ = web_client
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "幂等",
        "theme": "terracotta",
        "workdir": str(workdir),
    })

    first = client.delete(f"/api/history/{entry_id}")
    second = client.delete(f"/api/history/{entry_id}")

    assert first.status_code == 200
    assert second.status_code == 404


def test_delete_succeeds_when_workdir_already_missing(web_client, tmp_path):
    client, _ = web_client
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "目录已删",
        "theme": "terracotta",
        "workdir": str(workdir),
    })
    import shutil
    shutil.rmtree(workdir)

    response = client.delete(f"/api/history/{entry_id}")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_publish_returns_real_cli_result_on_success(web_client, tmp_path, monkeypatch):
    client, _ = web_client
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "可发布",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })
    monkeypatch.setattr(
        "webapp.app._run_cli",
        lambda *args, **kwargs: {
            "ok": True,
            "returncode": 0,
            "stdout": "Draft created! media_id: draft-abc",
            "stderr": "",
        },
    )

    response = client.post("/api/publish", json={"history_id": entry_id})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["returncode"] == 0
    assert payload["media_id"] == "draft-abc"
    assert history.get(entry_id)["status"] == "draft"


def test_publish_returns_real_returncode_and_stderr_on_failure(web_client, tmp_path, monkeypatch):
    client, _ = web_client
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "会失败",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })
    monkeypatch.setattr(
        "webapp.app._run_cli",
        lambda *args, **kwargs: {
            "ok": False,
            "returncode": 17,
            "stdout": "",
            "stderr": "Traceback: appsecret invalid",
        },
    )

    response = client.post("/api/publish", json={"history_id": entry_id})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["returncode"] == 17
    assert "appsecret invalid" in payload["stderr"]


def test_publish_does_not_change_article_status(web_client, tmp_path, monkeypatch):
    client, _ = web_client
    workdir = _make_workdir(tmp_path)
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "状态保持",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })
    monkeypatch.setattr(
        "webapp.app._run_cli",
        lambda *args, **kwargs: {
            "ok": True,
            "returncode": 0,
            "stdout": "Draft created! media_id: x",
            "stderr": "",
        },
    )

    client.post("/api/publish", json={"history_id": entry_id})

    assert history.get(entry_id)["status"] == "draft"


def test_health_works_without_d1_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("D1_API_URL", raising=False)
    monkeypatch.delenv("D1_API_TOKEN", raising=False)
    monkeypatch.delenv("D1_API_TOKEN_FILE", raising=False)

    import importlib
    from webapp import history, topics, jobs
    data_dir = tmp_path / "_data"
    data_dir.mkdir()
    history._init_store(data_dir / "history.json")
    topics._init_store(
        path=data_dir / "topics.json",
        corpus_path=Path(__file__).resolve().parent.parent / "references" / "knowledge-corpus.yaml",
    )
    jobs._init_store(data_dir / "jobs")
    monkeypatch.setenv("WS_DATA_DIR", str(data_dir))

    import importlib as _importlib
    from webapp import app as app_module
    _importlib.reload(app_module)

    client = app_module.app.test_client()

    response = client.get("/api/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["storage"] == "local"
    assert payload["corpus_size"] >= 1
    assert payload["history_count"] == 0
    assert payload["job_count"] == 0
