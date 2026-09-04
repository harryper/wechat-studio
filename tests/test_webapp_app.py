import base64
import copy
import importlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from webapp import history, jobs, model_settings


app_module = importlib.import_module("webapp.app")


SETTINGS_WITH_KEYS = {
    "schema_version": 1,
    "writing": {
        "provider_id": "custom-openai",
        "model": "writer",
        "base_url": "https://llm.example/v1",
        "api_key": "write-secret",
    },
    "image": {
        "provider_id": "cliproxy",
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

EFFECTIVE_WITH_KEYS = model_settings.EffectiveSettings(
    settings=SETTINGS_WITH_KEYS, source="local", warning=""
)
SETTINGS_WITH_FILE_URL = {
    **SETTINGS_WITH_KEYS,
    "writing": {
        **SETTINGS_WITH_KEYS["writing"],
        "base_url": "file:///etc/passwd",
    },
}
WRITING_FORM = SETTINGS_WITH_KEYS["writing"]
EXPECTED_RESOLVED_WRITING = {
    **SETTINGS_WITH_KEYS["writing"],
    "adapter": "openai_compatible",
}
IMAGE_FORM = SETTINGS_WITH_KEYS["image"]
EXPECTED_RESOLVED_IMAGE = {
    **SETTINGS_WITH_KEYS["image"],
    "adapter": "openai",
}


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
    monkeypatch.setattr(
        app_module.model_settings,
        "snapshot_settings",
        lambda: copy.deepcopy(SETTINGS_WITH_KEYS),
    )
    client = app_module.app.test_client()
    client.set_cookie(app_module.COOKIE_NAME, app_module.COOKIE_VALUE)
    yield client, executor


def test_model_settings_get_returns_full_keys_registry_and_no_store_headers(
    web_client, monkeypatch
):
    client, _ = web_client
    monkeypatch.setattr(
        app_module.model_settings,
        "load_effective_settings",
        lambda: EFFECTIVE_WITH_KEYS,
    )

    response = client.get("/api/model-settings")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "registry": app_module.registry_payload(),
        "settings": SETTINGS_WITH_KEYS,
        "source": "local",
        "warning": "",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/model-settings", None),
        ("put", "/api/model-settings", {"settings": SETTINGS_WITH_KEYS}),
        (
            "post",
            "/api/model-settings/test-writing",
            {"settings": WRITING_FORM},
        ),
        (
            "post",
            "/api/model-settings/test-image",
            {"settings": IMAGE_FORM, "confirm_charge": True},
        ),
    ],
)
def test_model_settings_endpoints_require_login_with_no_store_headers(
    method, path, body
):
    client = app_module.app.test_client()

    response = getattr(client, method)(path, json=copy.deepcopy(body))

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_model_settings_put_validates_before_saving(web_client, monkeypatch):
    client, _ = web_client
    saved = []
    monkeypatch.setattr(
        app_module.model_settings,
        "save_settings",
        lambda value: saved.append(value),
    )

    response = client.put(
        "/api/model-settings",
        json={"settings": copy.deepcopy(SETTINGS_WITH_FILE_URL)},
    )

    assert response.status_code == 400
    assert saved == []
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_model_settings_put_saves_and_returns_validated_form(web_client, monkeypatch):
    client, _ = web_client
    saved = []

    def save_settings(value):
        saved.append(copy.deepcopy(value))
        return copy.deepcopy(value)

    monkeypatch.setattr(app_module.model_settings, "save_settings", save_settings)

    response = client.put(
        "/api/model-settings",
        json={"settings": copy.deepcopy(SETTINGS_WITH_KEYS)},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "settings": SETTINGS_WITH_KEYS}
    assert saved == [SETTINGS_WITH_KEYS]


def test_model_settings_writing_connection_uses_unsaved_resolved_form(
    web_client, monkeypatch
):
    client, _ = web_client
    calls = []
    saves = []
    monkeypatch.setattr(
        app_module,
        "test_writing_connection",
        lambda value: calls.append(copy.deepcopy(value)) or {"ok": True},
        raising=False,
    )
    monkeypatch.setattr(
        app_module.model_settings,
        "save_settings",
        lambda value: saves.append(value),
    )

    response = client.post(
        "/api/model-settings/test-writing",
        json={"settings": copy.deepcopy(WRITING_FORM)},
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert calls == [EXPECTED_RESOLVED_WRITING]
    assert saves == []


def test_model_settings_image_test_requires_exact_charge_confirmation(
    web_client, monkeypatch
):
    client, _ = web_client
    calls = []
    monkeypatch.setattr(
        app_module,
        "generate_image_with_provider",
        lambda *args, **kwargs: calls.append((args, kwargs)),
        raising=False,
    )

    for confirm_charge in (None, False, 1, "true"):
        body = {"settings": copy.deepcopy(IMAGE_FORM)}
        if confirm_charge is not None:
            body["confirm_charge"] = confirm_charge
        response = client.post("/api/model-settings/test-image", json=body)
        assert response.status_code == 400
        assert "产生费用" in response.get_json()["error"]
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Pragma"] == "no-cache"

    assert calls == []


def test_model_settings_image_test_uses_registry_size_and_removes_original(
    web_client, monkeypatch
):
    client, _ = web_client
    calls = []
    saves = []

    def generate_image(prompt, output_path, settings, size):
        path = Path(output_path)
        calls.append((prompt, path, copy.deepcopy(settings), size))
        Image.new("RGB", (1000, 750), "#336699").save(path, format="PNG")
        return str(path)

    monkeypatch.setattr(
        app_module,
        "generate_image_with_provider",
        generate_image,
        raising=False,
    )
    monkeypatch.setattr(
        app_module.model_settings,
        "save_settings",
        lambda value: saves.append(value),
    )

    response = client.post(
        "/api/model-settings/test-image",
        json={"settings": copy.deepcopy(IMAGE_FORM), "confirm_charge": True},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["provider_id"] == "cliproxy"
    assert payload["model"] == "gpt-image-2"
    assert isinstance(payload["elapsed_ms"], int)
    assert payload["image"].startswith("data:image/jpeg;base64,")
    thumbnail_bytes = base64.b64decode(payload["image"].split(",", 1)[1])
    with Image.open(io.BytesIO(thumbnail_bytes)) as thumbnail:
        assert thumbnail.format == "JPEG"
        assert thumbnail.width <= 512
        assert thumbnail.height <= 512
    assert len(calls) == 1
    assert calls[0][2] == EXPECTED_RESOLVED_IMAGE
    assert calls[0][3] == "1024x1024"
    assert not calls[0][1].exists()
    assert saves == []


@pytest.mark.parametrize(
    ("path", "body", "patched_name"),
    [
        (
            "/api/model-settings/test-writing",
            {"settings": WRITING_FORM},
            "test_writing_connection",
        ),
        (
            "/api/model-settings/test-image",
            {"settings": IMAGE_FORM, "confirm_charge": True},
            "generate_image_with_provider",
        ),
    ],
)
def test_model_settings_connection_errors_redact_submitted_key(
    web_client, monkeypatch, path, body, patched_name
):
    client, _ = web_client
    secret = body["settings"]["api_key"]

    def fail(*args, **kwargs):
        raise RuntimeError(f"Authorization: Bearer {secret}")

    monkeypatch.setattr(app_module, patched_name, fail, raising=False)

    response = client.post(path, json=copy.deepcopy(body))

    assert response.status_code == 502
    serialized = response.get_data(as_text=True)
    assert secret not in serialized
    assert "***" in response.get_json()["error"]
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


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


def test_create_job_passes_full_snapshot_only_to_executor(web_client, monkeypatch):
    client, executor = web_client
    monkeypatch.setattr(
        app_module.model_settings,
        "snapshot_settings",
        lambda: SETTINGS_WITH_KEYS,
    )

    response = client.post("/api/jobs", json={
        "topic_id": "kb-001", "theme": "terracotta", "client": "",
    })

    job = jobs.get(response.get_json()["job_id"])
    assert "write-secret" not in json.dumps(job, ensure_ascii=False)
    assert job["payload"]["models"] == EXPECTED_AUDIT
    assert executor.calls[0][1] == (job["id"], SETTINGS_WITH_KEYS)
    assert executor.calls[0][1][1] is not SETTINGS_WITH_KEYS
    assert executor.calls[0][1][1]["writing"] is not SETTINGS_WITH_KEYS["writing"]


def test_later_save_does_not_mutate_queued_snapshot(web_client, monkeypatch):
    client, executor = web_client
    mutable = copy.deepcopy(SETTINGS_WITH_KEYS)
    monkeypatch.setattr(
        app_module.model_settings,
        "snapshot_settings",
        lambda: copy.deepcopy(mutable),
    )

    client.post("/api/jobs", json={
        "topic_id": "kb-001", "theme": "terracotta", "client": "",
    })
    mutable["writing"]["model"] = "new-model"

    assert executor.calls[0][1][1]["writing"]["model"] == "writer"


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


@pytest.mark.parametrize(
    ("stage", "extra"),
    [
        ("article", {}),
        ("images", {}),
        ("image", {"role": "inline-4"}),
    ],
)
def test_regenerate_job_passes_full_snapshot_only_to_executor(
    web_client, tmp_path, monkeypatch, stage, extra
):
    client, executor = web_client
    calls = 0

    def snapshot_settings():
        nonlocal calls
        calls += 1
        return copy.deepcopy(SETTINGS_WITH_KEYS)

    monkeypatch.setattr(app_module.model_settings, "snapshot_settings", snapshot_settings)
    workdir = tmp_path / "work"
    workdir.mkdir()
    entry_id = history.add({
        "topic_id": "kb-001", "title": "x", "category": "cognitive_bias",
        "theme": "terracotta", "workdir": str(workdir), "image_mode": "real",
    })

    response = client.post(
        f"/api/history/{entry_id}/regenerate",
        json={"stage": stage, **extra},
    )

    job = jobs.get(response.get_json()["job_id"])
    assert calls == 1
    assert "write-secret" not in json.dumps(job, ensure_ascii=False)
    assert job["payload"]["models"] == EXPECTED_AUDIT
    assert executor.calls[0][1] == (job["id"], SETTINGS_WITH_KEYS)
