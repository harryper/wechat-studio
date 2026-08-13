import json
from pathlib import Path

from webapp import jobs, pipeline


def test_file_backed_job_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_JOBS_DIR", tmp_path / "jobs")
    job = jobs.create("full", {"topic": {"id": "kb-001"}})
    assert jobs.get(job["id"])["status"] == "queued"
    jobs.update(job["id"], status="running", progress=42)
    loaded = jobs.get(job["id"])
    assert loaded["status"] == "running"
    assert loaded["progress"] == 42
    assert jobs.get("../escape") is None


def test_preflight_accepts_five_complete_images(tmp_path):
    workdir = tmp_path / "work"
    images = workdir / "images"
    images.mkdir(parents=True)
    refs = ["images/cover.jpg", *[f"images/inline-{i}.jpg" for i in range(1, 5)]]
    markdown = "# 为什么我们总会在重要决策中忽略基础概率\n\n## 摘要\n\n正文内容。\n"
    for i, ref in enumerate(refs):
        markdown += f"\n![图{i}]({ref})\n"
        (workdir / ref).write_bytes(b"image")
    (workdir / "article.md").write_text(markdown, encoding="utf-8")
    (workdir / "image-status.json").write_text(
        json.dumps({"cover": "real", **{f"inline-{i}": "real" for i in range(1, 5)}}),
        encoding="utf-8",
    )
    result = pipeline.preflight({"workdir": str(workdir), "client": ""})
    assert result["publishable"] is True
    assert not [item for item in result["checks"] if item["level"] == "error"]


def test_preflight_blocks_blacklisted_title_and_missing_cover(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "article.md").write_text("# 震惊：一个标题\n\n## 摘要\n\n正文", encoding="utf-8")
    result = pipeline.preflight({"workdir": str(workdir), "client": ""})
    assert result["publishable"] is False
    errors = {item["key"] for item in result["checks"] if item["level"] == "error"}
    assert {"cover", "blacklist"}.issubset(errors)


def test_full_job_persists_completed_history(tmp_path, monkeypatch):
    from webapp import history

    data_dir = tmp_path / "data"
    monkeypatch.setattr(jobs, "_JOBS_DIR", data_dir / "jobs")
    monkeypatch.setattr(history, "_DATA_DIR", data_dir)
    monkeypatch.setattr(history, "_HISTORY_FILE", data_dir / "history.json")
    history._entries.clear()
    history._next_id = 1
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "article.md").write_text(
        "# 这是一个足够长的学术定义式测试标题\n\n## 摘要\n\n正文",
        encoding="utf-8",
    )
    topic = {"id": "kb-001", "title": "原主题", "category": "psychology"}
    job = jobs.create("full", {"topic": topic, "theme": "terracotta", "client": ""})
    monkeypatch.setattr(
        pipeline, "write_article_to_workdir",
        lambda topic, client=None: (workdir, ["images/cover.jpg"]),
    )
    monkeypatch.setattr(pipeline, "generate_images_in_workdir", lambda *args: "real")
    monkeypatch.setattr(pipeline, "_write_preview_html", lambda wd, theme: None)
    monkeypatch.setattr(
        pipeline, "assess_workdir",
        lambda wd, client=None: {
            "title": "这是一个足够长的学术定义式测试标题",
            "blacklist": {"passed": True, "hits": [], "suggestion": None},
            "humanness_score": 20,
            "client": "",
            "playbook_applied": False,
        },
    )
    pipeline.run_job(job["id"])
    finished = jobs.get(job["id"])
    assert finished["status"] == "completed"
    assert finished["progress"] == 100
    assert finished["result"]["history_id"] == 1
    assert history.get(1)["image_mode"] == "real"
