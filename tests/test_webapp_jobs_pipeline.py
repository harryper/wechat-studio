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
        "prompt": "用户编辑后的 Prompt",
        "models": EXPECTED_AUDIT,
    })

    def write_article(topic, workdir=None, client=None, writing_settings=None, prompt=None):
        captured["writing_settings"] = writing_settings
        captured["prompt"] = prompt
        return workdir_fixture, image_rels

    def generate_images(workdir, topic, rels, image_settings):
        captured["image_settings"] = image_settings
        return "real"

    workdir_fixture = workdir
    monkeypatch.setattr(pipeline, "write_article_to_workdir", write_article)
    monkeypatch.setattr(pipeline, "generate_images_in_workdir", generate_images)
    monkeypatch.setattr(pipeline, "_write_preview_html", lambda wd, theme: None)
    return job["id"]


def test_d1_backed_job_lifecycle(memory_d1):
    job = jobs.create("full", {"topic": {"id": "kb-001"}})
    assert jobs.get(job["id"])["status"] == "queued"
    jobs.update(job["id"], status="running", progress=42)
    loaded = jobs.get(job["id"])
    assert loaded["status"] == "running"
    assert loaded["progress"] == 42
    assert jobs.get("../escape") is None


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
        lambda topic, client=None, writing_settings=None, prompt=None: (workdir, ["images/cover.jpg"]),
    )
    monkeypatch.setattr(pipeline, "generate_images_in_workdir", lambda *args: "real")
    monkeypatch.setattr(pipeline, "_write_preview_html", lambda wd, theme: None)
    pipeline.run_job(job["id"], SETTINGS_WITH_KEYS)
    finished = jobs.get(job["id"])
    assert finished["status"] == "completed"
    assert finished["progress"] == 100
    assert finished["result"]["history_id"] == entry_id
    assert history.get(entry_id)["image_mode"] == "real"
    assert history.get(entry_id)["status"] == "draft"
    assert "assessment" not in finished["result"]


def test_pipeline_uses_one_snapshot_for_writing_and_images(
    tmp_path, monkeypatch, memory_d1
):
    captured = {}
    job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)

    pipeline.run_job(job_id, SETTINGS_WITH_KEYS)

    assert captured["writing_settings"] == SETTINGS_WITH_KEYS["writing"]
    assert captured["image_settings"] == SETTINGS_WITH_KEYS["image"]
    assert captured["prompt"] == "用户编辑后的 Prompt"


def test_article_regeneration_reuses_saved_prompt(tmp_path, monkeypatch, memory_d1):
    from webapp import history

    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "article.md").write_text(
        "# 这是一个足够长的学术定义式测试标题\n\n## 摘要\n\n正文",
        encoding="utf-8",
    )
    topic = {
        "id": "custom-1",
        "title": "用户主题",
        "category": "自定义主题",
        "prompt": "历史任务保存的 Prompt",
    }
    entry_id = history.add({
        "topic_id": topic["id"], "title": topic["title"], "category": topic["category"],
        "theme": "terracotta", "client": "", "status": "draft", "workdir": str(workdir),
    })
    job = jobs.create("article", {"history_id": entry_id, "topic": topic})
    captured = {}

    def rewrite(topic, workdir=None, client=None, writing_settings=None, prompt=None):
        captured["prompt"] = prompt
        return workdir, []

    monkeypatch.setattr(pipeline, "write_article_to_workdir", rewrite)
    monkeypatch.setattr(pipeline, "_write_preview_html", lambda wd, theme: None)

    pipeline.run_job(job["id"], SETTINGS_WITH_KEYS)

    assert captured["prompt"] == "历史任务保存的 Prompt"


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
