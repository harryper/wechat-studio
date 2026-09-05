import json
from pathlib import Path

from webapp import jobs, pipeline


SETTINGS_WITH_KEYS = {
    "schema_version": 1,
    "writing": {
        "provider_id": "custom-openai",
        "adapter": "openai_compatible",
        "model": "writer",
        "base_url": "https://llm.example/v1",
        "api_key": "write-secret",
    },
    "image": {
        "provider_id": "cliproxy",
        "adapter": "openai",
        "model": "gpt-image-2",
        "base_url": "http://127.0.0.1:8317/v1",
        "api_key": "image-secret",
    },
}

EXPECTED_AUDIT = {
    "writing": {
        "provider_id": "custom-openai",
        "adapter": "openai_compatible",
        "model": "writer",
    },
    "image": {
        "provider_id": "cliproxy",
        "adapter": "openai",
        "model": "gpt-image-2",
    },
}


def install_full_job_fakes(monkeypatch, tmp_path, captured):
    from webapp import history

    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "article.md").write_text(
        "# 这是一个足够长的学术定义式测试标题\n\n## 摘要\n\n正文",
        encoding="utf-8",
    )
    image_rels = [
        "images/cover.jpg",
        *[f"images/inline-{index}.jpg" for index in range(1, 5)],
    ]
    topic = {"id": "kb-001", "title": "原主题", "category": "psychology"}
    entry_id = history.add({
        "topic_id": "kb-001", "title": "原主题", "category": "psychology",
        "theme": "terracotta", "client": "", "status": "generating",
    })
    job = jobs.create("full", {
        "topic": topic, "theme": "terracotta", "client": "", "history_id": entry_id,
        "models": EXPECTED_AUDIT,
    })

    def write_article(topic, workdir=None, client=None, writing_settings=None):
        captured["writing_settings"] = writing_settings
        return workdir_fixture, image_rels

    def generate_images(workdir, topic, rels, image_settings):
        captured["image_settings"] = image_settings
        return "real"

    workdir_fixture = workdir
    monkeypatch.setattr(pipeline, "write_article_to_workdir", write_article)
    monkeypatch.setattr(pipeline, "generate_images_in_workdir", generate_images)
    monkeypatch.setattr(pipeline, "_write_preview_html", lambda wd, theme: None)
    monkeypatch.setattr(
        pipeline,
        "assess_workdir",
        lambda wd, client=None: {
            "title": "这是一个足够长的学术定义式测试标题",
            "blacklist": {"passed": True, "hits": [], "suggestion": None},
            "humanness_score": 20,
            "client": "",
            "playbook_applied": False,
        },
    )
    monkeypatch.setattr(pipeline, "preflight", lambda entry: {"publishable": True})
    return job["id"]


def test_d1_backed_job_lifecycle(memory_d1):
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


def test_full_job_persists_completed_history(tmp_path, monkeypatch, memory_d1):
    from webapp import history

    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "article.md").write_text(
        "# 这是一个足够长的学术定义式测试标题\n\n## 摘要\n\n正文",
        encoding="utf-8",
    )
    topic = {"id": "kb-001", "title": "原主题", "category": "psychology"}
    entry_id = history.add({
        "topic_id": "kb-001", "title": "原主题", "category": "psychology",
        "theme": "terracotta", "client": "", "status": "generating",
    })
    job = jobs.create("full", {
        "topic": topic, "theme": "terracotta", "client": "", "history_id": entry_id,
    })
    monkeypatch.setattr(
        pipeline, "write_article_to_workdir",
        lambda topic, client=None, writing_settings=None: (workdir, ["images/cover.jpg"]),
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
    pipeline.run_job(job["id"], SETTINGS_WITH_KEYS)
    finished = jobs.get(job["id"])
    assert finished["status"] == "completed"
    assert finished["progress"] == 100
    assert finished["result"]["history_id"] == entry_id
    assert history.get(entry_id)["image_mode"] == "real"


def test_pipeline_uses_one_snapshot_for_writing_and_images(
    tmp_path, monkeypatch, memory_d1
):
    captured = {}
    job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)

    pipeline.run_job(job_id, SETTINGS_WITH_KEYS)

    assert captured["writing_settings"] == SETTINGS_WITH_KEYS["writing"]
    assert captured["image_settings"] == SETTINGS_WITH_KEYS["image"]


def test_pipeline_failure_persisted_to_d1_is_redacted(
    tmp_path, monkeypatch, memory_d1
):
    captured = {}
    job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)
    monkeypatch.setattr(
        pipeline,
        "write_article_to_workdir",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "write-secret and image-secret at https://user:pass@example.test/v1"
            )
        ),
    )

    pipeline.run_job(job_id, SETTINGS_WITH_KEYS)

    serialized = json.dumps(jobs.get(job_id), ensure_ascii=False)
    assert "write-secret" not in serialized
    assert "image-secret" not in serialized
    assert "user:pass" not in serialized
    assert jobs.get(job_id)["error"] == (
        "RuntimeError: *** and *** at https://example.test/v1"
    )


def test_pipeline_redacts_api_key_that_equals_exception_type_prefix(
    tmp_path, monkeypatch, memory_d1
):
    captured = {}
    job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)
    settings = {
        **SETTINGS_WITH_KEYS,
        "writing": {
            **SETTINGS_WITH_KEYS["writing"],
            "api_key": "RuntimeError",
        },
    }
    monkeypatch.setattr(
        pipeline,
        "write_article_to_workdir",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("request failed")),
    )

    pipeline.run_job(job_id, settings)

    failed = jobs.get(job_id)
    assert "RuntimeError" not in json.dumps(failed, ensure_ascii=False)
    assert failed["error"] == "***: request failed"
