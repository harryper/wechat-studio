import base64
import copy
import importlib
import io
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image

from webapp import history, jobs, model_settings, writing_prompt_settings


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

RESOLVED_SETTINGS_WITH_KEYS = {
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

EFFECTIVE_WITH_KEYS = model_settings.EffectiveSettings(
    settings=RESOLVED_SETTINGS_WITH_KEYS, source="local", warning=""
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


class IdCollectingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.input_types = {}
        self.textarea_placeholders = {}
        self.textarea_values = {}
        self._textarea_id = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.add(element_id)
            if tag == "input":
                self.input_types[element_id] = values.get("type", "text")
            elif tag == "textarea":
                self._textarea_id = element_id
                self.textarea_placeholders[element_id] = values.get("placeholder", "")
                self.textarea_values[element_id] = ""

    def handle_data(self, data):
        if self._textarea_id:
            self.textarea_values[self._textarea_id] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self._textarea_id = None


@pytest.fixture
def web_client(tmp_path, monkeypatch, memory_d1):
    executor = FakeExecutor()
    monkeypatch.setattr(app_module, "JOB_EXECUTOR", executor)
    monkeypatch.setattr(
        app_module.model_settings,
        "snapshot_settings",
        lambda: copy.deepcopy(RESOLVED_SETTINGS_WITH_KEYS),
    )
    prompt_path = tmp_path / "writing-prompt.json"
    monkeypatch.setattr(writing_prompt_settings, "WRITING_PROMPT_PATH", prompt_path)
    client = app_module.app.test_client()
    client.set_cookie(app_module.COOKIE_NAME, app_module.COOKIE_VALUE)
    yield client, executor


def test_index_renders_model_settings_dialog_contract(web_client):
    client, _ = web_client

    response = client.get("/")
    rendered = response.get_data(as_text=True)
    parser = IdCollectingParser()
    parser.feed(rendered)

    required = {
        "btn-model-settings",
        "model-settings-backdrop",
        "settings-tab-writing",
        "settings-tab-image",
        "writing-provider",
        "writing-model",
        "writing-base-url",
        "writing-api-key",
        "image-provider",
        "image-model",
        "image-base-url",
        "image-api-key",
        "btn-test-writing",
        "btn-test-image",
        "btn-save-model-settings",
        "btn-cancel-model-settings",
    }

    assert required <= parser.ids
    assert parser.input_types["writing-api-key"] == "password"
    assert parser.input_types["image-api-key"] == "password"
    assert "API Key 将完整返回给已登录浏览器" in rendered
    assert "仅影响之后提交的新任务" in rendered


def test_index_renders_direct_article_creation_contract(web_client):
    client, _ = web_client

    response = client.get("/")
    rendered = response.get_data(as_text=True)
    parser = IdCollectingParser()
    parser.feed(rendered)

    assert {
        "article-subject",
        "article-key-points",
        "article-origin",
        "article-prompt",
        "btn-save-prompt",
        "btn-reset-prompt",
        "advanced-settings",
        "theme-description",
    } <= parser.ids
    assert "topic-search" not in parser.ids
    assert "topic-center" not in parser.ids
    assert "btn-preflight" not in parser.ids
    assert "发布前检查" not in rendered
    assert "待检查" not in rendered
    assert "可发布" not in rendered
    initial_prompt = parser.textarea_values["article-prompt"]
    assert "微信公众号·知识科普" in initial_prompt
    assert "{{文章主题}}" in initial_prompt


def test_article_context_placeholders_explain_how_inputs_affect_writing(web_client):
    client, _ = web_client

    rendered = client.get("/").get_data(as_text=True)
    parser = IdCollectingParser()
    parser.feed(rendered)

    assert parser.textarea_placeholders["article-key-points"] == (
        "填写希望文章重点回答的观点或问题，每行一条；AI 会优先围绕这些内容展开"
    )
    assert parser.textarea_placeholders["article-origin"] == (
        "填写相关事实、案例、素材来源或写作限制；AI 会将其作为文章的参考依据"
    )


def test_index_explains_writing_style_presets(web_client):
    client, _ = web_client

    rendered = client.get("/").get_data(as_text=True)
    parser = IdCollectingParser()
    parser.feed(rendered)

    assert {
        "writing-style-description",
        "writing-style-name",
        "writing-style-summary",
        "writing-style-suitable",
        "writing-style-method",
        "writing-style-avoid",
        "writing-style-source",
    } <= parser.ids
    assert "写作风格" in rendered
    assert "理性科普｜清晰、严谨、通俗易读" in rendered
    assert "现实思辨｜冷静、锋利、克制" in rendered
    assert "青年共鸣｜温暖、有态度、不说教" in rendered
    assert "仅影响文章写作，不影响图片和排版" in rendered


def test_index_renders_lazy_history_drawer_contract(web_client):
    client, _ = web_client

    response = client.get("/")
    rendered = response.get_data(as_text=True)
    parser = IdCollectingParser()
    parser.feed(rendered)

    assert {
        "btn-history",
        "history-backdrop",
        "history-drawer",
        "history-list",
        "btn-refresh-history",
        "btn-close-history",
    } <= parser.ids
    assert "历史预览" not in rendered
    assert "打开后加载历史记录" in rendered
    assert "已回看历史" not in rendered
    script = rendered.split("<script>", 1)[1].split("</script>", 1)[0]
    startup = script.rsplit("updateThemeDescription();", 1)[1]
    startup = startup.split("const activeJob", 1)[0]
    assert "refreshHistory()" not in startup
    assert "async function openHistory()" in script
    open_history = script.split("async function openHistory()", 1)[1]
    open_history = open_history.split("async function refreshHistory()", 1)[0]
    assert "await refreshHistory();" in open_history


def test_writing_prompt_api_saves_and_returns_default_template(web_client):
    client, _ = web_client
    template = "请围绕 {{文章主题}} 写作。\n要点：\n{{关键要点}}"

    saved = client.put("/api/writing-prompt", json={"prompt": template})
    loaded = client.get("/api/writing-prompt")

    assert saved.status_code == 200
    assert saved.get_json() == {"ok": True, "prompt": template}
    assert loaded.get_json() == {
        "ok": True,
        "prompt": template,
        "system_default": writing_prompt_settings.DEFAULT_PROMPT_TEMPLATE,
    }
    assert loaded.headers["Cache-Control"] == "private, no-store"


def test_saved_writing_prompt_is_loaded_into_page_after_refresh(web_client):
    client, _ = web_client
    template = "刷新后继续使用 {{文章主题}}"
    assert client.put("/api/writing-prompt", json={"prompt": template}).status_code == 200

    response = client.get("/")
    rendered = response.get_data(as_text=True)
    parser = IdCollectingParser()
    parser.feed(rendered)

    assert parser.textarea_values["article-prompt"] == template
    assert response.headers["Cache-Control"] == "private, no-store"


def test_writing_prompt_api_rejects_empty_template(web_client):
    client, _ = web_client

    response = client.put("/api/writing-prompt", json={"prompt": "   "})

    assert response.status_code == 400
    assert "Prompt" in response.get_json()["error"]


def test_index_localizes_internal_theme_names(web_client):
    client, _ = web_client

    rendered = client.get("/").get_data(as_text=True)

    assert '>专业·清爽</option>' in rendered
    assert '>科技·现代</option>' in rendered
    assert '>暖色·编辑</option>' in rendered
    assert '>professional-clean</option>' not in rendered


def test_index_model_settings_focus_trap_redirects_external_and_dialog_focus(web_client):
    client, _ = web_client

    rendered = client.get("/").get_data(as_text=True)

    assert "if (!settingsDialog.contains(document.activeElement)) {" in rendered
    assert "} else if (activeElement === settingsDialog) {" in rendered
    assert "(event.shiftKey ? last : first).focus();" in rendered


def test_index_model_tests_bind_status_to_locked_request_snapshot(web_client):
    client, _ = web_client

    rendered = client.get("/").get_data(as_text=True)
    test_function = rendered[
        rendered.index("async function runSettingsTest"):
        rendered.index("async function saveModelSettings")
    ]

    assert test_function.index("const requestSnapshot") < test_function.index("await fetch")
    assert "settings: requestSnapshot.settings" in test_function
    assert "requestSettings.model === requestSettings.api_key ? '***'" in test_function
    assert "setSettingsTestControlsLocked(true);" in test_function
    assert "setSettingsTestControlsLocked(false);" in test_function
    assert "window.confirm('测试会实际生成一张图片并产生费用，是否继续？')" in test_function
    assert "confirm_charge: true" in test_function

    status_function = rendered[
        rendered.index("function renderSettingsTestStatus"):
        rendered.index("async function runSettingsTest")
    ]
    assert "requestSnapshot.provider" in status_function
    assert "requestSnapshot.model" in status_function
    assert "Provider：" in status_function
    assert "模型：" in status_function
    assert "耗时：" in status_function
    assert "状态：成功" in status_function
    assert "状态：失败" in status_function
    assert "redactSettingsTestError" in status_function

    lock_function = rendered[
        rendered.index("function setSettingsTestControlsLocked"):
        rendered.index("function closeModelSettings")
    ]
    for control_id in (
        "settings-tab-writing",
        "settings-tab-image",
        "writing-provider",
        "writing-model",
        "writing-base-url",
        "writing-api-key",
        "btn-toggle-writing-api-key",
        "btn-test-writing",
        "image-provider",
        "image-model",
        "image-base-url",
        "image-api-key",
        "btn-toggle-image-api-key",
        "btn-test-image",
        "btn-save-model-settings",
        "btn-cancel-model-settings",
    ):
        assert repr(control_id) in lock_function


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
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


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
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


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
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


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


def test_article_prompt_preview_uses_unsaved_user_input(web_client):
    client, _ = web_client

    response = client.post("/api/article-prompt", json={
        "subject": "AI 如何改变个人知识管理",
        "category": "效率工具",
        "key_points": ["信息收集不等于知识形成", "输出会倒逼理解"],
        "origin": "来自用户的实践记录",
    })

    assert response.status_code == 200
    prompt = response.get_json()["prompt"]
    assert "AI 如何改变个人知识管理" in prompt
    assert "效率工具" in prompt
    assert "信息收集不等于知识形成" in prompt
    assert "来自用户的实践记录" in prompt
    assert response.headers["Cache-Control"] == "private, no-store"


def test_create_job_accepts_subject_and_persists_edited_prompt(web_client, memory_d1):
    client, _ = web_client
    edited_prompt = "  你是一名资深编辑。只根据用户提供的资料写作。\n"

    response = client.post("/api/jobs", json={
        "subject": "AI 如何改变个人知识管理",
        "category": "效率工具",
        "key_points": ["输出会倒逼理解"],
        "origin": "用户访谈",
        "prompt": edited_prompt,
        "theme": "terracotta",
        "client": "",
    })

    assert response.status_code == 202
    job = jobs.get(response.get_json()["job_id"])
    topic = memory_d1.topics[job["payload"]["topic"]["id"]]
    assert job["payload"]["prompt"] == edited_prompt
    assert topic["title"] == "AI 如何改变个人知识管理"
    assert topic["context"]["prompt"] == edited_prompt


def test_create_job_rebuilds_stale_default_prompt_from_current_subject(web_client):
    client, _ = web_client

    response = client.post("/api/jobs", json={
        "subject": "新的文章主题",
        "prompt": "仍然指向旧主题的默认 Prompt",
        "prompt_mode": "default",
    })

    assert response.status_code == 202
    job = jobs.get(response.get_json()["job_id"])
    assert "新的文章主题" in job["payload"]["prompt"]
    assert "仍然指向旧主题" not in job["payload"]["prompt"]


def test_create_job_renders_user_prompt_template_with_current_subject(web_client):
    client, _ = web_client

    response = client.post("/api/jobs", json={
        "subject": "动态注入的主题",
        "key_points": ["动态要点"],
        "origin": "动态背景",
        "prompt": "主题：{{文章主题}}\n背景：{{背景资料}}\n{{关键要点}}",
        "prompt_mode": "template",
    })

    assert response.status_code == 202
    prompt = jobs.get(response.get_json()["job_id"])["payload"]["prompt"]
    assert "主题：动态注入的主题" in prompt
    assert "背景：动态背景" in prompt
    assert "- 动态要点" in prompt
    assert "{{" not in prompt


@pytest.mark.parametrize("field,value", [
    ("subject", 123),
    ("category", []),
    ("origin", {}),
    ("client", False),
    ("prompt", ["write"]),
    ("key_points", False),
])
def test_article_input_endpoints_reject_non_text_fields(web_client, field, value):
    client, _ = web_client
    payload = {"subject": "合法主题", field: value}

    preview = client.post("/api/article-prompt", json=payload)
    create = client.post("/api/jobs", json=payload)

    assert preview.status_code == 400
    assert create.status_code == 400


def test_default_prompt_mode_ignores_oversized_stale_browser_value(web_client):
    client, _ = web_client

    response = client.post("/api/jobs", json={
        "subject": "以当前输入为准",
        "prompt_mode": "default",
        "prompt": "旧" * 40_001,
    })

    assert response.status_code == 202
    job = jobs.get(response.get_json()["job_id"])
    assert "以当前输入为准" in job["payload"]["prompt"]


def test_create_job_rejects_empty_subject(web_client):
    client, _ = web_client

    response = client.post("/api/jobs", json={"subject": "   ", "prompt": "write"})

    assert response.status_code == 400
    assert response.get_json()["phase"] == "input"
    assert "文章主题" in response.get_json()["error"]


def test_create_job_passes_full_snapshot_only_to_executor(web_client, monkeypatch):
    client, executor = web_client
    monkeypatch.setattr(
        app_module.model_settings,
        "snapshot_settings",
        lambda: RESOLVED_SETTINGS_WITH_KEYS,
    )

    response = client.post("/api/jobs", json={
        "topic_id": "kb-001", "theme": "terracotta", "client": "",
    })

    job = jobs.get(response.get_json()["job_id"])
    assert "write-secret" not in json.dumps(job, ensure_ascii=False)
    assert job["payload"]["models"] == EXPECTED_AUDIT
    assert executor.calls[0][1] == (job["id"], RESOLVED_SETTINGS_WITH_KEYS)
    assert executor.calls[0][1][1] is not RESOLVED_SETTINGS_WITH_KEYS
    assert executor.calls[0][1][1]["writing"] is not RESOLVED_SETTINGS_WITH_KEYS["writing"]


def test_later_save_does_not_mutate_queued_snapshot(web_client, monkeypatch):
    client, executor = web_client
    mutable = copy.deepcopy(RESOLVED_SETTINGS_WITH_KEYS)
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


def test_removed_preflight_endpoint_returns_not_found(web_client, tmp_path):
    client, _ = web_client
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "无需检查",
        "theme": "terracotta",
        "workdir": str(tmp_path),
        "status": "draft",
    })

    response = client.get(f"/api/history/{entry_id}/preflight")

    assert response.status_code == 404
    assert response.get_json() == {"error": "not found"}


def test_publish_runs_without_preflight_gate(
    web_client, tmp_path, monkeypatch, memory_d1
):
    client, _ = web_client
    workdir = tmp_path / "publish"
    workdir.mkdir()
    (workdir / "article.md").write_text(
        "# 可以直接发布的文章\n\n## 摘要\n\n正文", encoding="utf-8"
    )
    entry_id = history.add({
        "topic_id": "kb-001",
        "title": "可以直接发布的文章",
        "theme": "terracotta",
        "workdir": str(workdir),
        "status": "draft",
    })
    monkeypatch.setattr(app_module, "_run_cli", lambda *args, **kwargs: {
        "ok": True,
        "returncode": 0,
        "stdout": "Draft created! media_id: draft-123",
        "stderr": "",
    })

    response = client.post("/api/publish", json={"history_id": entry_id})

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert "preflight" not in response.get_json()
    assert memory_d1.publications[-1]["status"] == "pushed"


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
        return copy.deepcopy(RESOLVED_SETTINGS_WITH_KEYS)

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
    assert executor.calls[0][1] == (job["id"], RESOLVED_SETTINGS_WITH_KEYS)
