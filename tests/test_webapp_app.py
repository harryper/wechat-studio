import importlib
from pathlib import Path

import pytest

from webapp import history, jobs


app_module = importlib.import_module("webapp.app")


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))
        return None


@pytest.fixture
def web_client(tmp_path, monkeypatch, memory_d1):
    executor = FakeExecutor()
    monkeypatch.setattr(app_module, "JOB_EXECUTOR", executor)
    client = app_module.app.test_client()
    client.set_cookie(app_module.COOKIE_NAME, app_module.COOKIE_VALUE)
    yield client, executor


def test_create_generation_job_returns_202(web_client):
    client, executor = web_client
    response = client.post("/api/jobs", json={
        "topic_id": "kb-001", "theme": "terracotta", "client": "",
    })
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "queued"
    assert history.get(payload["history_id"])["status"] == "generating"
    assert jobs.get(payload["job_id"])["kind"] == "full"
    assert len(executor.calls) == 1


def test_topic_center_lists_and_creates_custom_topic(web_client):
    client, _ = web_client
    listed = client.get("/api/topics?status=available&q=幸存者")
    assert listed.status_code == 200
    assert listed.get_json()["topics"][0]["id"] == "kb-001"

    created = client.post("/api/topics", json={
        "title": "自定义产品主题",
        "category": "product",
        "key_points": ["第一条", "第二条"],
    })
    assert created.status_code == 201
    payload = created.get_json()["topic"]
    assert payload["source"] == "custom"
    assert payload["status"] == "available"


def test_article_edit_saves_and_rerenders(web_client, tmp_path, monkeypatch):
    client, _ = web_client
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "article.md").write_text("# 旧标题\n\n## 摘要\n\n旧正文", encoding="utf-8")
    entry_id = history.add({
        "topic_id": "kb-001", "title": "旧标题", "category": "cognitive_bias",
        "theme": "terracotta", "workdir": str(workdir), "image_mode": "real",
    })
    monkeypatch.setattr(app_module, "_write_preview_html", lambda wd, theme: (wd / "article.html").write_text("ok"))
    response = client.put(f"/api/history/{entry_id}/article", json={
        "markdown": "# 新标题这是一个足够长的测试标题\n\n## 摘要\n\n新正文",
    })
    assert response.status_code == 200
    assert history.get(entry_id)["title"] == "新标题这是一个足够长的测试标题"
    assert "新正文" in (workdir / "article.md").read_text(encoding="utf-8")


def test_regenerate_single_image_queues_job(web_client, tmp_path):
    client, executor = web_client
    workdir = tmp_path / "work"
    workdir.mkdir()
    entry_id = history.add({
        "topic_id": "kb-001", "title": "x", "category": "cognitive_bias",
        "theme": "terracotta", "workdir": str(workdir), "image_mode": "real",
    })
    response = client.post(f"/api/history/{entry_id}/regenerate", json={
        "stage": "image", "role": "inline-4",
    })
    assert response.status_code == 202
    job = jobs.get(response.get_json()["job_id"])
    assert job["kind"] == "image"
    assert job["payload"]["role"] == "inline-4"
    assert len(executor.calls) == 1
