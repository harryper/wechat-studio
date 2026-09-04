# Web Model Settings Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent Web settings dialog that configures OpenAI-compatible or Anthropic Messages writing models and one strict, non-fallback image model.

**Architecture:** A shared Provider Registry declares model capabilities, a local JSON store owns secrets, and protocol adapters isolate outbound requests. Flask snapshots settings when each job is submitted, persists only non-secret audit metadata to D1, and passes the full snapshot to the in-process worker.

**Tech Stack:** Python 3.11+, Flask, requests, anthropic SDK, Pillow, vanilla HTML/CSS/JavaScript, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-05-model-settings-design.md`

## Global Constraints

- Writing protocols are limited to exactly `openai_compatible` and `anthropic_messages`.
- Web image generation calls exactly one selected Provider; any failure fails the job without fallback or placeholder creation.
- API keys persist only in `webapp/_data/model-settings.json`, with file mode `0600`; they never enter D1, article history, browser storage, or logs.
- Authenticated `GET /api/model-settings` returns the full API key as requested and all settings endpoints send `Cache-Control: private, no-store` plus `Pragma: no-cache`.
- Settings changes affect only jobs submitted after the save; queued and running jobs keep their in-memory submission snapshot.
- CLI and OpenClaw retain the existing `.env/config.yaml` provider-chain behavior.
- OpenAI-compatible writing uses the existing `requests` dependency; do not add the OpenAI SDK.
- Preserve the approved image-prompt work currently present in `README.md`, `SKILL.md`, `webapp/render.py`, tests, references, and `dist/openclaw`.
- Complete Setup 0 before Task 1: checkpoint those approved changes in their own commit, then use `superpowers:using-git-worktrees` to establish a clean isolated execution tree from that baseline. Never mix the image-prompt checkpoint into model-settings commits.

## File Structure

| File | Responsibility |
|---|---|
| `toolkit/model_registry.py` | Immutable writing/image Provider metadata, defaults, lookup, and submitted-config validation |
| `toolkit/model_security.py` | URL validation, safe host extraction, and secret/error redaction shared by adapters and Flask |
| `toolkit/llm_adapters.py` | OpenAI-compatible and Anthropic Messages text requests behind one interface |
| `webapp/model_settings.py` | `.env/config.yaml` bootstrap, local JSON validation, atomic `0600` persistence, snapshots and audit projection |
| `scripts/write_article.py` | Article prompt/cleanup plus delegation to the selected writing adapter |
| `toolkit/image_gen.py` | New explicit single-Provider image entry point; existing provider-chain entry point remains unchanged |
| `webapp/render.py` | Requires explicit Web writing/image settings and removes Web placeholder fallback |
| `webapp/pipeline.py` | Consumes one immutable settings snapshot for the entire job |
| `webapp/app.py` | Settings APIs, test APIs, snapshot-at-submit behavior, and no-store headers |
| `webapp/templates/index.html` | Top-right settings trigger, tabs, forms, secret reveal, tests and save interactions |
| `tests/test_model_registry.py` | Registry, URL and redaction contracts |
| `tests/test_model_settings.py` | Migration, persistence, permissions, corruption and snapshot tests |
| `tests/test_llm_adapters.py` | Both writing protocol request/response contracts and sanitized failures |
| `tests/test_image_gen.py` | Explicit single-Provider image behavior without changing chain behavior |
| `tests/test_webapp_render.py` | Strict Web image failures and explicit settings propagation |
| `tests/test_webapp_jobs_pipeline.py` | Pipeline snapshot use and failure semantics |
| `tests/test_webapp_app.py` | Settings endpoints, secret containment, executor arguments and rendered dialog contract |

---

### Setup 0: Checkpoint approved image-prompt work and isolate execution

**Files already modified:**
- `README.md`
- `SKILL.md`
- `dist/openclaw/SKILL.md`
- `dist/openclaw/references/visual-prompts.md`
- `references/visual-prompts.md`
- `tests/test_webapp_render.py`
- `webapp/render.py`

- [ ] **Step 1: Verify the existing approved change set**

Run these commands separately:

```bash
git status --short
git diff --check
python3 -m pytest -q tests/test_webapp_render.py
```

Expected: exactly the seven files above are modified, diff check exits 0, and the render tests pass. If other user changes are present at execution time, stop and separate them without discarding them.

- [ ] **Step 2: Commit only the approved image-prompt work**

```bash
git add README.md SKILL.md dist/openclaw/SKILL.md dist/openclaw/references/visual-prompts.md references/visual-prompts.md tests/test_webapp_render.py webapp/render.py
git diff --cached --check
git commit -m "feat: ground article images in source content"
```

- [ ] **Step 3: Create the isolated implementation worktree**

Invoke `superpowers:using-git-worktrees` and follow it completely. Create the feature branch/worktree from the commit made in Step 2, verify `git status --short` is empty there, and run the skill's required baseline tests before Task 1.

---

### Task 1: Provider Registry and shared secret safety

**Files:**
- Create: `toolkit/model_registry.py`
- Create: `toolkit/model_security.py`
- Create: `tests/test_model_registry.py`

**Interfaces:**
- Produces: `ProviderSpec`, `get_provider(kind, provider_id)`, `registry_payload()`, `resolve_provider_config(kind, raw)`.
- Produces: `validate_base_url(value)`, `safe_base_host(value)`, `redact_sensitive(value, secrets=())`.
- Consumes: only Python standard library.

- [ ] **Step 1: Write failing Registry and security tests**

```python
from toolkit.model_registry import (
    ProviderConfigError,
    get_provider,
    registry_payload,
    resolve_provider_config,
)
from toolkit.model_security import redact_sensitive, safe_base_host, validate_base_url


def test_writing_registry_uses_only_two_protocols():
    protocols = {item["adapter"] for item in registry_payload()["writing"]}
    assert protocols == {"openai_compatible", "anthropic_messages"}

def test_resolve_provider_config_applies_defaults_without_hiding_overrides():
    resolved = resolve_provider_config("writing", {
        "provider_id": "openai",
        "model": "custom-model",
        "base_url": "https://gateway.example/v1",
        "api_key": "secret-key",
    })
    assert resolved == {
        "provider_id": "openai",
        "adapter": "openai_compatible",
        "model": "custom-model",
        "base_url": "https://gateway.example/v1",
        "api_key": "secret-key",
    }

def test_validate_base_url_rejects_userinfo_and_non_http_schemes():
    for value in ("file:///etc/passwd", "https://user:pass@example.com/v1"):
        try:
            validate_base_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)

def test_redact_sensitive_removes_keys_and_sensitive_query_values():
    message = "failed https://example.com/v1?api_key=abc token=xyz secret-key"
    assert redact_sensitive(message, secrets=("secret-key",)) == (
        "failed https://example.com/v1?api_key=*** token=*** ***"
    )
    assert safe_base_host("http://host.docker.internal:8317/v1") == "host.docker.internal:8317"
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `python3 -m pytest -q tests/test_model_registry.py`

Expected: FAIL during collection because `toolkit.model_registry` and `toolkit.model_security` do not exist.

- [ ] **Step 3: Implement immutable Provider specs and validation**

Use a frozen dataclass with these exact fields:

```python
@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider_id: str
    label: str
    kind: Literal["writing", "image"]
    adapter: str
    default_model: str
    default_base_url: str
    requires_api_key: bool = True
    requires_base_url: bool = True
    supports_connection_test: bool = True
    test_size: str = ""
```


Declare these stable IDs:

```python
WRITING_PROVIDERS = (
    ProviderSpec("minimax-anthropic", "MiniMax · Anthropic", "writing", "anthropic_messages", "MiniMax-M3", "https://api.minimaxi.com/anthropic"),
    ProviderSpec("openai", "OpenAI", "writing", "openai_compatible", "gpt-5.5", "https://api.openai.com/v1"),
    ProviderSpec("anthropic", "Anthropic", "writing", "anthropic_messages", "claude-sonnet-5", "https://api.anthropic.com"),
    ProviderSpec("kimi", "Kimi / Moonshot", "writing", "openai_compatible", "kimi-k3", "https://api.moonshot.cn/v1"),
    ProviderSpec("deepseek", "DeepSeek", "writing", "openai_compatible", "deepseek-v4-pro", "https://api.deepseek.com"),
    ProviderSpec("volcengine", "豆包 / 火山方舟", "writing", "openai_compatible", "doubao-seed-2-1-turbo-260628", "https://ark.cn-beijing.volces.com/api/v3"),
    ProviderSpec("custom-openai", "自定义 OpenAI-compatible", "writing", "openai_compatible", "", ""),
    ProviderSpec("custom-anthropic", "自定义 Anthropic Messages", "writing", "anthropic_messages", "", ""),
)
```

Image specs must map `cliproxy` and `openai` to adapter `openai`, `seedream` to `seedream`, and `minimax` to `minimax`; include exact current defaults from `config.yaml`. Add `custom-openai-image` with empty model/Base URL. Reject duplicate or unknown IDs, empty required fields, unknown kind, and any adapter outside the allowed set for its kind. Expose `supports_connection_test` and `test_size` in `registry_payload()`.

Implement URL parsing with `urllib.parse.urlsplit`. Redaction must replace known secret literals, URL userinfo, Authorization values, and query/key-value names matching `api_key|token|key|secret|password`, case-insensitively.

- [ ] **Step 4: Run Registry tests and the existing suite**

Run: `python3 -m pytest -q tests/test_model_registry.py tests/test_image_gen.py tests/test_write_article_client.py`

Expected: PASS.

- [ ] **Step 5: Commit the Registry unit**

```bash
git add toolkit/model_registry.py toolkit/model_security.py tests/test_model_registry.py
git commit -m "feat: add model provider registry"
```

---

### Task 2: Local model settings persistence and legacy bootstrap

**Files:**
- Create: `webapp/model_settings.py`
- Create: `tests/test_model_settings.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `resolve_provider_config()` from Task 1 and `toolkit.env_config` semantics.
- Produces: `load_settings(path=SETTINGS_PATH) -> dict`, `save_settings(settings, path=SETTINGS_PATH) -> dict`, `bootstrap_settings(path, environ, config_path) -> dict`.
- Produces: `load_effective_settings(path=SETTINGS_PATH, environ=None, config_path=None) -> EffectiveSettings`, `snapshot_settings() -> dict`, `audit_settings(settings) -> dict`.
- Produces constant: `SETTINGS_PATH = SKILL_DIR / "webapp" / "_data" / "model-settings.json"`.

- [ ] **Step 1: Write failing persistence tests**

```python
import json
import os

from webapp import model_settings

def test_save_is_atomic_private_and_round_trips_full_keys(tmp_path):
    path = tmp_path / "model-settings.json"
    settings = {
        "schema_version": 1,
        "writing": {"provider_id": "custom-openai", "model": "writer", "base_url": "https://llm.example/v1", "api_key": "write-secret"},
        "image": {"provider_id": "custom-openai-image", "model": "image-model", "base_url": "https://image.example/v1", "api_key": "image-secret"},
    }
    assert model_settings.save_settings(settings, path) == model_settings.load_settings(path)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert list(tmp_path.glob("*.tmp")) == []

def test_bootstrap_imports_legacy_env_without_mutating_it(tmp_path):
    env = {
        "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
        "ANTHROPIC_API_KEY": "legacy-write",
        "ANTHROPIC_MODEL": "MiniMax-M3",
        "IMAGE_PROVIDER_ORDER": "cliproxy,seedream,minimax",
        "CLIPROXY_IMAGE_API_KEY": "legacy-image",
        "CLIPROXY_IMAGE_BASE_URL": "http://host.docker.internal:8317/v1",
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    settings = model_settings.bootstrap_settings(tmp_path / "settings.json", env, config_path)
    assert settings["writing"]["provider_id"] == "minimax-anthropic"
    assert settings["image"]["provider_id"] == "cliproxy"
    assert env["ANTHROPIC_API_KEY"] == "legacy-write"

def test_corrupt_file_is_preserved_and_reports_legacy_fallback(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    result = model_settings.load_effective_settings(path, LEGACY_ENV, config_path)
    assert result.source == "legacy-fallback"
    assert result.warning.startswith("模型设置文件损坏")
    assert path.read_text(encoding="utf-8") == "{broken"

def test_audit_projection_never_contains_secrets_or_base_url():
    audit = model_settings.audit_settings(SETTINGS_WITH_KEYS)
    assert audit == {
        "writing": {"provider_id": "custom-openai", "adapter": "openai_compatible", "model": "writer"},
        "image": {"provider_id": "cliproxy", "adapter": "openai", "model": "gpt-image-2"},
    }
```

Define `CONFIG_YAML` as a literal complete YAML string and `LEGACY_ENV` plus `SETTINGS_WITH_KEYS` as literal complete dictionaries in the test module; do not derive expected values with production helpers.

- [ ] **Step 2: Run persistence tests and verify they fail**

Run: `python3 -m pytest -q tests/test_model_settings.py`

Expected: FAIL because `webapp.model_settings` does not exist.

- [ ] **Step 3: Implement validation, atomic writes and bootstrap**

Use this returned wrapper for fallback visibility:

```python
@dataclass(frozen=True, slots=True)
class EffectiveSettings:
    settings: dict
    source: Literal["local", "legacy-bootstrap", "legacy-fallback"]
    warning: str = ""
```

`save_settings()` must validate both sections before opening a temp file, create the parent with mode `0700`, write JSON with `ensure_ascii=False`, flush and `os.fsync()`, call `os.chmod(temp_path, 0o600)`, then `os.replace()`. Clean the temp file on exceptions.

`bootstrap_settings()` must parse `config.yaml` with `yaml.safe_load`, expand `${NAME}` and `${NAME:-default}` against the supplied environment mapping, and choose only the first ID in `IMAGE_PROVIDER_ORDER`. It must never assign into the supplied mapping or write `.env/config.yaml`.

Persist only the user form fields (`schema_version`, `provider_id`, and optional `model`/`base_url`/`api_key` overrides). `load_effective_settings()` and `snapshot_settings()` must resolve omitted model/Base URL values against the current Registry on every read and include the resolved `adapter`; this preserves dynamic Registry defaults. `bootstrap_settings()` writes the imported file exactly once when it is absent. A corrupt existing file is never replaced by fallback data.

Add an explicit `.gitignore` line for `webapp/_data/model-settings.json`, even though `_data` is currently ignored, so the secret boundary remains visible during future ignore refactors.

- [ ] **Step 4: Run persistence and environment tests**

Run: `python3 -m pytest -q tests/test_model_settings.py tests/test_env_config.py tests/test_diagnose_config.py`

Expected: PASS.

- [ ] **Step 5: Commit local settings persistence**

```bash
git add .gitignore webapp/model_settings.py tests/test_model_settings.py
git commit -m "feat: persist web model settings locally"
```

---

### Task 3: Two writing protocol adapters

**Files:**
- Create: `toolkit/llm_adapters.py`
- Create: `tests/test_llm_adapters.py`

**Interfaces:**
- Consumes: validated writing settings from `resolve_provider_config("writing", raw)` and `redact_sensitive()`.
- Produces: `generate_text(prompt, settings, *, max_tokens=4096, timeout=240) -> str`.
- Produces: `extract_openai_text(payload, provider_id) -> str` for validated Chat Completions response extraction.
- Produces: `test_writing_connection(settings, *, timeout=30) -> dict` returning `ok`, `provider_id`, `model`, `elapsed_ms`, and either `text` or `error`.

- [ ] **Step 1: Write failing adapter contract tests**

```python
def test_openai_compatible_posts_chat_completions(monkeypatch):
    captured = {}
    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResponse(200, {"choices": [{"message": {"content": "# 正文"}}]})
    monkeypatch.setattr(llm_adapters.requests, "post", fake_post)
    result = llm_adapters.generate_text("写文章", OPENAI_SETTINGS, max_tokens=123, timeout=9)
    assert result == "# 正文"
    assert captured == {
        "url": "https://gateway.example/v1/chat/completions",
        "headers": {"Authorization": "Bearer write-secret", "Content-Type": "application/json"},
        "json": {"model": "writer", "max_tokens": 123, "messages": [{"role": "user", "content": "写文章"}]},
        "timeout": 9,
    }

def test_anthropic_messages_uses_selected_endpoint_key_and_model(monkeypatch):
    fake = FakeAnthropicResponse("# 正文")
    factory = CapturingAnthropicFactory(fake)
    monkeypatch.setattr(llm_adapters.anthropic, "Anthropic", factory)
    assert llm_adapters.generate_text("写文章", ANTHROPIC_SETTINGS) == "# 正文"
    assert factory.client_kwargs == {"base_url": "https://anthropic.example", "api_key": "anthropic-secret"}
    assert factory.message_kwargs["model"] == "claude-model"

def test_empty_or_malformed_responses_fail_with_provider_context():
    with pytest.raises(RuntimeError, match="custom-openai.*返回为空"):
        llm_adapters.extract_openai_text({"choices": []}, "custom-openai")

def test_adapter_errors_do_not_expose_api_key_or_url_credentials(monkeypatch):
    monkeypatch.setattr(llm_adapters.requests, "post", raising_post_with_secret_url)
    with pytest.raises(RuntimeError) as exc:
        llm_adapters.generate_text("x", OPENAI_SETTINGS)
    message = str(exc.value)
    assert "write-secret" not in message
    assert "user:pass" not in message
```

The fakes must mirror the complete response fields consumed by production code: status, JSON body, `raise_for_status()`, `content`, and Anthropic text blocks.

Define `OPENAI_SETTINGS` and `ANTHROPIC_SETTINGS` as complete literal dictionaries in the test module. Implement `FakeResponse.raise_for_status()` to raise `requests.HTTPError` for status codes at or above 400; implement `FakeResponse.json()` to return its constructor payload. `CapturingAnthropicFactory.__call__()` must save its keyword arguments and return an object whose `messages.create(**kwargs)` stores `message_kwargs` and returns `FakeAnthropicResponse`. `raising_post_with_secret_url()` must raise an exception whose message contains both `write-secret` and `https://user:pass@example.com/v1`, so the redaction assertion proves both values are removed.

- [ ] **Step 2: Run tests and verify the missing-module failure**

Run: `python3 -m pytest -q tests/test_llm_adapters.py`

Expected: FAIL during collection because `toolkit.llm_adapters` does not exist.

- [ ] **Step 3: Implement both adapters and connection testing**

Normalize the OpenAI URL as `base_url.rstrip("/") + "/chat/completions"`. Send one non-streaming request. On non-2xx responses, include status and a redacted, length-limited response detail. Extract only `choices[0].message.content`.

For Anthropic, instantiate `anthropic.Anthropic(base_url=..., api_key=...)` and call `messages.create(model=..., max_tokens=..., timeout=..., messages=[...])`. Concatenate only blocks with string `.text`.

`test_writing_connection()` must call `generate_text("只回复 OK", ..., max_tokens=8)` and measure elapsed time with `time.monotonic()`. It returns errors instead of raising, after redaction.

Log only adapter, Provider ID, model, safe Base URL host, phase and elapsed time. Never pass response headers, request headers, request JSON, full URL, or exception text to logging before redaction.

- [ ] **Step 4: Run adapter and legacy client tests**

Run: `python3 -m pytest -q tests/test_llm_adapters.py tests/test_write_article_client.py`

Expected: PASS.

- [ ] **Step 5: Commit protocol adapters**

```bash
git add toolkit/llm_adapters.py tests/test_llm_adapters.py
git commit -m "feat: add configurable writing adapters"
```

---

### Task 4: Route article writing through the selected adapter

**Files:**
- Modify: `scripts/write_article.py`
- Modify: `tests/test_write_article_client.py`
- Modify: `webapp/render.py`
- Modify: `tests/test_webapp_render.py`

**Interfaces:**
- Consumes: `generate_text()` from Task 3.
- Changes: `write_article(topic, *, client=None, settings=None, model=None, max_tokens=4096, timeout=240) -> str`.
- Changes: `write_article_to_workdir(topic, workdir=None, client=None, writing_settings=None) -> tuple[Path, list[str]]`.

- [ ] **Step 1: Write failing settings-propagation tests**

```python
def test_write_article_uses_runtime_settings(monkeypatch):
    captured = {}
    def fake_generate(prompt, settings, **kwargs):
        captured.update(prompt=prompt, settings=settings, kwargs=kwargs)
        return "# 新标题\n\n## 摘要\n\n正文"
    monkeypatch.setattr(write_article, "generate_text", fake_generate)
    result = write_article.write_article(TOPIC, settings=WRITING_SETTINGS, max_tokens=777, timeout=12)
    assert result.startswith("# 新标题")
    assert captured["settings"] == WRITING_SETTINGS
    assert captured["kwargs"] == {"max_tokens": 777, "timeout": 12}

def test_write_article_legacy_env_is_converted_to_anthropic_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://legacy.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "legacy-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "legacy-model")
    captured = capture_generate_text(monkeypatch)
    write_article.write_article(TOPIC)
    assert captured["settings"] == {
        "provider_id": "legacy-anthropic",
        "adapter": "anthropic_messages",
        "base_url": "https://legacy.example",
        "api_key": "legacy-key",
        "model": "legacy-model",
    }

def test_write_article_to_workdir_forwards_writing_settings(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(render, "write_article", lambda topic, **kwargs: captured.update(kwargs) or ARTICLE)
    render.write_article_to_workdir(TOPIC, tmp_path, writing_settings=WRITING_SETTINGS)
    assert captured["settings"] == WRITING_SETTINGS
```

Define these values directly in the relevant test modules:

```python
TOPIC = {"title": "损失厌恶", "category": "认知偏差", "key_points": ["损失比同额收益更显著"]}
WRITING_SETTINGS = {
    "provider_id": "custom-openai", "adapter": "openai_compatible",
    "model": "writer", "base_url": "https://llm.example/v1", "api_key": "write-secret",
}
ARTICLE = "# 新标题\n\n## 摘要\n\n正文"
```

Implement `capture_generate_text(monkeypatch)` locally: create an empty dictionary, patch `write_article.generate_text` with a function that stores its `settings` argument and returns `ARTICLE`, then return that dictionary.

- [ ] **Step 2: Run the focused tests and verify settings are not accepted**

Run: `python3 -m pytest -q tests/test_write_article_client.py tests/test_webapp_render.py -k "runtime_settings or legacy_env or forwards_writing"`

Expected: FAIL with unexpected keyword arguments or missing `generate_text` imports.

- [ ] **Step 3: Replace direct SDK use with adapter delegation**

Keep `_build_prompt()`, `_strip_code_fence()` and `_enforce_title()` unchanged. Build the exact legacy settings dictionary when `settings is None`; apply the existing optional `model` argument as a copy-on-write override. Call `generate_text()` once, then run the existing cleanup. Remove direct response-block parsing from `write_article()` because it belongs to the adapter.

In `render.write_article_to_workdir()`, pass `settings=writing_settings` to `write_article()`.

- [ ] **Step 4: Run writing and render tests**

Run: `python3 -m pytest -q tests/test_write_article_client.py tests/test_webapp_render.py`

Expected: PASS.

- [ ] **Step 5: Commit article integration**

```bash
git add scripts/write_article.py webapp/render.py tests/test_write_article_client.py tests/test_webapp_render.py
git commit -m "refactor: route article writing through adapters"
```

---

### Task 5: Explicit single-Provider Web image generation

**Files:**
- Modify: `toolkit/image_gen.py`
- Modify: `webapp/render.py`
- Modify: `tests/test_image_gen.py`
- Modify: `tests/test_webapp_render.py`

**Interfaces:**
- Produces: `generate_image_with_provider(prompt, output_path, provider_settings, size="cover") -> str`.
- Changes: `generate_images_in_workdir(workdir, topic, image_rels, image_settings) -> Literal["real"]`.
- Changes: `generate_single_image_in_workdir(workdir, topic, role, image_settings) -> Literal["real"]`.
- Preserves: `generate_image(prompt, output_path, size="cover", config=None)` exactly, including provider-chain fallback.

- [ ] **Step 1: Write failing strict-image tests**

```python
def test_generate_image_with_provider_builds_only_selected_provider(tmp_path, monkeypatch):
    calls = []
    class FakeProvider:
        def resolve_size(self, size): return "1536x1024"
        def generate(self, prompt, size):
            calls.append((prompt, size))
            return b"image-bytes"
    monkeypatch.setattr(image_gen, "_build_provider_from_entry", lambda entry: FakeProvider())
    out = tmp_path / "image.jpg"
    image_gen.generate_image_with_provider("prompt", out, IMAGE_SETTINGS)
    assert out.read_bytes() == b"image-bytes"
    assert calls == [("prompt", "1536x1024")]

def test_web_image_failure_raises_without_placeholder(tmp_path, monkeypatch):
    workdir = make_article_workdir(tmp_path)
    monkeypatch.setattr(render, "generate_image_with_provider", raising_image_call)
    with pytest.raises(RuntimeError, match="quota"):
        render.generate_images_in_workdir(workdir, TOPIC, render.default_image_rels(), IMAGE_SETTINGS)
    assert not (workdir / "image-status.json").exists()
    assert list((workdir / "images").iterdir()) == []

def test_legacy_generate_image_still_falls_back(fake_chain, tmp_path):
    first = FakeProvider("first", [RuntimeError("first failed")])
    second = FakeProvider("second", [b"clean"])
    fake_chain(first, second)
    image_gen.generate_image("prompt", tmp_path / "out.jpg", config={})
    assert len(second.prompts) == 1
```

Define `IMAGE_SETTINGS` directly in both test modules:

```python
IMAGE_SETTINGS = {
    "provider_id": "cliproxy", "adapter": "openai", "model": "gpt-image-2",
    "base_url": "http://127.0.0.1:8317/v1", "api_key": "image-secret",
}
```

In `tests/test_webapp_render.py`, implement `make_article_workdir(tmp_path)` by creating `work/images`, writing an `article.md` with one abstract and four H2 sections, and returning `work`. Implement `raising_image_call(*args, **kwargs)` as `raise RuntimeError("quota")`. Reuse the existing module-level `TOPIC`; if it does not exist at execution time, define the same complete literal used in Task 4.

- [ ] **Step 2: Run strict-image tests and verify failure**

Run: `python3 -m pytest -q tests/test_image_gen.py tests/test_webapp_render.py -k "selected_provider or failure_raises or still_falls_back"`

Expected: FAIL because `generate_image_with_provider` and required `image_settings` behavior do not exist.

- [ ] **Step 3: Implement the explicit entry point and remove Web fallback**

Convert validated image settings to the existing provider entry shape:

```python
entry = {
    "id": settings["provider_id"],
    "provider": settings["adapter"],
    "model": settings["model"],
    "base_url": settings["base_url"],
    "api_key": settings["api_key"],
}
```

Build one provider with `_build_provider_from_entry(entry)`, resolve size, generate once, enforce the existing 5 MB compression rule, and write output. Do not call `_build_provider_chain()` in this path.

Wrap Provider errors at this boundary with Provider/model context and `redact_sensitive(..., secrets=(settings["api_key"],))`; this sanitized exception is the only image error allowed to reach `pipeline.run_job()` or D1.

In `webapp/render.py`, remove the try/except that writes `_placeholder_image()` for Web generation. Generate sequentially with the explicit entry point; only after all five succeed write `image-status.json` with every role set to `real`. If a later image fails, leave successful intermediate images for diagnosis but do not render a successful preview or write a success status. For single-image regeneration, write to a sibling temporary path and replace the prior image only after success, so a failed replacement preserves the reviewed image.

- [ ] **Step 4: Run image and render suites**

Run: `python3 -m pytest -q tests/test_image_gen.py tests/test_webapp_render.py`

Expected: PASS, including all legacy chain tests.

- [ ] **Step 5: Commit strict Web images**

```bash
git add toolkit/image_gen.py webapp/render.py tests/test_image_gen.py tests/test_webapp_render.py
git commit -m "feat: use one strict image model in web jobs"
```

---

### Task 6: Immutable model snapshots in background jobs

**Files:**
- Modify: `webapp/pipeline.py`
- Modify: `webapp/app.py`
- Modify: `tests/test_webapp_jobs_pipeline.py`
- Modify: `tests/test_webapp_app.py`

**Interfaces:**
- Consumes: `snapshot_settings()` and `audit_settings()` from Task 2.
- Changes: `pipeline.run_job(job_id: str, settings_snapshot: dict) -> None`.
- Produces helper: `_submit_model_job(job: dict, settings_snapshot: dict) -> None` in `webapp/app.py`.

- [ ] **Step 1: Write failing job snapshot tests**

```python
def test_create_job_passes_full_snapshot_only_to_executor(web_client, monkeypatch):
    client, executor = web_client
    monkeypatch.setattr(app_module.model_settings, "snapshot_settings", lambda: SETTINGS_WITH_KEYS)
    response = client.post("/api/jobs", json={"topic_id": "kb-001", "theme": "terracotta", "client": ""})
    job = jobs.get(response.get_json()["job_id"])
    assert "write-secret" not in json.dumps(job, ensure_ascii=False)
    assert job["payload"]["models"] == EXPECTED_AUDIT
    assert executor.calls[0][1] == (job["id"], SETTINGS_WITH_KEYS)

def test_pipeline_uses_one_snapshot_for_writing_and_images(tmp_path, monkeypatch):
    captured = {}
    job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)
    pipeline.run_job(job_id, SETTINGS_WITH_KEYS)
    assert captured["writing_settings"] == SETTINGS_WITH_KEYS["writing"]
    assert captured["image_settings"] == SETTINGS_WITH_KEYS["image"]


def test_later_save_does_not_mutate_queued_snapshot(web_client, monkeypatch):
    client, executor = web_client
    mutable = copy.deepcopy(SETTINGS_WITH_KEYS)
    monkeypatch.setattr(app_module.model_settings, "snapshot_settings", lambda: copy.deepcopy(mutable))
    client.post("/api/jobs", json={"topic_id": "kb-001", "theme": "terracotta", "client": ""})
    mutable["writing"]["model"] = "new-model"
    assert executor.calls[0][1][1]["writing"]["model"] == "writer"

def test_pipeline_failure_persisted_to_d1_is_redacted(tmp_path, monkeypatch, memory_d1):
    captured = {}
    job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)
    monkeypatch.setattr(
        pipeline, "write_article_to_workdir",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("write-secret at https://user:pass@example.test/v1")),
    )
    pipeline.run_job(job_id, SETTINGS_WITH_KEYS)
    serialized = json.dumps(jobs.get(job_id), ensure_ascii=False)
    assert "write-secret" not in serialized
    assert "user:pass" not in serialized
```

Define complete literal `SETTINGS_WITH_KEYS` and `EXPECTED_AUDIT` dictionaries in both affected test modules; the former uses the Task 4 writing settings and Task 5 image settings, while the latter contains only `provider_id`, `adapter`, and `model` for each section. Add `import copy` and `import json` to `tests/test_webapp_app.py`.

Implement `install_full_job_fakes(monkeypatch, tmp_path, captured)` in `tests/test_webapp_jobs_pipeline.py` as follows: create a real history entry and `full` job through the existing `memory_d1`-backed helpers; patch `write_article_to_workdir` to record `writing_settings` and return a prepared workdir plus five image paths; patch `generate_images_in_workdir` to record its fourth positional `image_settings` argument and return `"real"`; patch `_write_preview_html`, `assess_workdir`, and `preflight` with deterministic successful fakes. Return the created job ID and use that return value instead of an undefined `JOB_ID`:

```python
job_id = install_full_job_fakes(monkeypatch, tmp_path, captured)
pipeline.run_job(job_id, SETTINGS_WITH_KEYS)
```

- [ ] **Step 2: Run snapshot tests and verify existing executor signature fails**

Run: `python3 -m pytest -q tests/test_webapp_app.py tests/test_webapp_jobs_pipeline.py -k snapshot`

Expected: FAIL because executor receives only `job_id` and pipeline has no settings parameter.

- [ ] **Step 3: Thread the snapshot through every full and regeneration path**

At request time call `snapshot_settings()` once, add `models=audit_settings(snapshot)` to the D1 payload, and pass `copy.deepcopy(snapshot)` as the second executor argument. Apply the same flow to article, all-images and single-image regeneration.

In `pipeline.run_job()`, never call the settings store. Pass `settings_snapshot["writing"]` to `write_article_to_workdir()` and `settings_snapshot["image"]` to both image functions. A full job uses the same snapshot for writing and all five images. In the outer exception handler, call `redact_sensitive()` with both snapshot API keys before persisting `job.error`; this is defense in depth even though adapters also sanitize their failures.

- [ ] **Step 4: Run Web app and pipeline tests**

Run: `python3 -m pytest -q tests/test_webapp_app.py tests/test_webapp_jobs_pipeline.py tests/test_webapp_render.py`

Expected: PASS.

- [ ] **Step 5: Commit job snapshot semantics**

```bash
git add webapp/app.py webapp/pipeline.py tests/test_webapp_app.py tests/test_webapp_jobs_pipeline.py
git commit -m "feat: snapshot model settings per web job"
```

---

### Task 7: Authenticated settings and paid test APIs

**Files:**
- Modify: `webapp/app.py`
- Modify: `tests/test_webapp_app.py`

**Interfaces:**
- Consumes: Registry payload, settings persistence, `test_writing_connection()`, `generate_image_with_provider()`, Pillow and redaction helpers.
- Produces the four `/api/model-settings` endpoints defined in the spec.

- [ ] **Step 1: Write failing API behavior tests**

```python
def test_settings_get_returns_full_keys_with_no_store_headers(web_client, monkeypatch):
    client, _ = web_client
    monkeypatch.setattr(app_module.model_settings, "load_effective_settings", lambda: EFFECTIVE_WITH_KEYS)
    response = client.get("/api/model-settings")
    assert response.status_code == 200
    assert response.get_json()["settings"]["writing"]["api_key"] == "write-secret"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"

def test_settings_endpoints_require_login():
    client = app_module.app.test_client()
    assert client.get("/api/model-settings").status_code == 401

def test_put_validates_before_saving(web_client, monkeypatch):
    client, _ = web_client
    saved = []
    monkeypatch.setattr(app_module.model_settings, "save_settings", lambda value: saved.append(value))
    response = client.put("/api/model-settings", json={"settings": SETTINGS_WITH_FILE_URL})
    assert response.status_code == 400
    assert saved == []

def test_writing_connection_test_does_not_save_form_values(web_client, monkeypatch):
    client, _ = web_client
    calls = []
    monkeypatch.setattr(app_module, "test_writing_connection", lambda value: calls.append(value) or {"ok": True})
    response = client.post("/api/model-settings/test-writing", json={"settings": WRITING_FORM})
    assert response.get_json()["ok"] is True
    assert calls == [EXPECTED_RESOLVED_WRITING]

def test_image_test_requires_charge_confirmation(web_client):
    client, _ = web_client
    response = client.post("/api/model-settings/test-image", json={"settings": IMAGE_FORM})
    assert response.status_code == 400
    assert "产生费用" in response.get_json()["error"]
```

Define these fixtures as complete literals near the tests:

```python
EFFECTIVE_WITH_KEYS = model_settings.EffectiveSettings(
    settings=SETTINGS_WITH_KEYS, source="local", warning=""
)
SETTINGS_WITH_FILE_URL = {
    **SETTINGS_WITH_KEYS,
    "writing": {**SETTINGS_WITH_KEYS["writing"], "base_url": "file:///etc/passwd"},
}
WRITING_FORM = SETTINGS_WITH_KEYS["writing"]
EXPECTED_RESOLVED_WRITING = SETTINGS_WITH_KEYS["writing"]
IMAGE_FORM = SETTINGS_WITH_KEYS["image"]
```

Import `model_settings` from `webapp` in the test module. Use `copy.deepcopy()` when passing or mutating these dictionaries so no test shares mutable state.

- [ ] **Step 2: Run API tests and verify 404 failures**

Run: `python3 -m pytest -q tests/test_webapp_app.py -k model_settings`

Expected: FAIL because all four endpoints return 404.

- [ ] **Step 3: Implement settings CRUD, tests and no-store responses**

Create a response helper that applies both cache headers to success and error responses. `GET` returns:

```json
{
  "ok": true,
  "registry": {"writing": [], "image": []},
  "settings": {"schema_version": 1, "writing": {}, "image": {}},
  "source": "local",
  "warning": ""
}
```

`PUT` accepts `{ "settings": { ... } }` and returns the validated saved form. Never log the request body.

The writing test accepts `{ "settings": { ...writing fields... } }`, validates only that writing section, and calls `test_writing_connection()` without saving.

The image test rejects missing `confirm_charge: true`, validates one image section, creates a `TemporaryDirectory`, generates one image using the Registry `test_size`, opens it with Pillow, applies `thumbnail((512, 512))`, returns a JPEG data URL, and lets the temporary directory delete the source. Return Provider, model and elapsed time. Sanitize all exceptions with the submitted key included in the secret list.

- [ ] **Step 4: Run all Flask and settings tests**

Run: `python3 -m pytest -q tests/test_webapp_app.py tests/test_model_settings.py tests/test_llm_adapters.py`

Expected: PASS.

- [ ] **Step 5: Commit settings APIs**

```bash
git add webapp/app.py tests/test_webapp_app.py
git commit -m "feat: add authenticated model settings APIs"
```

---

### Task 8: Top-right settings dialog

**Files:**
- Modify: `webapp/templates/index.html`
- Modify: `tests/test_webapp_app.py`

**Interfaces:**
- Consumes: the four Task 7 endpoints.
- Produces DOM IDs: `btn-model-settings`, `model-settings-backdrop`, `settings-tab-writing`, `settings-tab-image`, `writing-provider`, `writing-model`, `writing-base-url`, `writing-api-key`, `image-provider`, `image-model`, `image-base-url`, `image-api-key`, `btn-test-writing`, `btn-test-image`, `btn-save-model-settings`, `btn-cancel-model-settings`.

- [ ] **Step 1: Write a failing rendered-dialog contract test**

```python
from html.parser import HTMLParser

def test_index_renders_model_settings_dialog_contract(web_client):
    client, _ = web_client
    response = client.get("/")
    parser = IdCollectingParser()
    parser.feed(response.get_data(as_text=True))
    required = {
        "btn-model-settings", "model-settings-backdrop",
        "settings-tab-writing", "settings-tab-image",
        "writing-provider", "writing-model", "writing-base-url", "writing-api-key",
        "image-provider", "image-model", "image-base-url", "image-api-key",
        "btn-test-writing", "btn-test-image",
        "btn-save-model-settings", "btn-cancel-model-settings",
    }
    assert required <= parser.ids
    assert parser.input_types["writing-api-key"] == "password"
    assert parser.input_types["image-api-key"] == "password"
```

Implement `IdCollectingParser` inside the test file so the test exercises rendered HTML rather than reading the template source:

```python
class IdCollectingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.input_types = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.add(element_id)
            if tag == "input":
                self.input_types[element_id] = values.get("type", "text")
```

- [ ] **Step 2: Run the dialog contract test and verify missing IDs**

Run: `python3 -m pytest -q tests/test_webapp_app.py::test_index_renders_model_settings_dialog_contract`

Expected: FAIL because `btn-model-settings` and the dialog controls are absent.

- [ ] **Step 3: Add the modal markup, responsive styling and state isolation**

Add `⚙ 设置` before “健康检查”. Use a dedicated settings backdrop instead of overloading the existing result modal. The modal is `min(680px, calc(100vw - 32px))`, scrolls internally, traps focus while open, closes on Cancel or Escape, and does not close while a connection test is running.

On open, fetch `/api/model-settings`; build provider options from `registry`, populate complete values, and keep the returned object only in a closure-scoped variable. Provider changes apply that Provider's defaults and previously edited in-dialog values. Eye buttons toggle only the matching input's `type`.

On writing test, POST the unsaved writing form and render inline status. On image test, call `window.confirm("测试会实际生成一张图片并产生费用，是否继续？")`; only then POST `{settings, confirm_charge: true}` and show the returned thumbnail.

On save, PUT `{settings: {schema_version: 1, writing, image}}`; close only after success. On close, blank both key inputs, clear the closure state and revoke any object URLs. Do not use `localStorage`, `sessionStorage`, URL parameters or `console.log` for settings.

- [ ] **Step 4: Add API/UI copy assertions and run Web tests**

Extend the rendered contract test to assert the visible warnings “API Key 将完整返回给已登录浏览器” and “仅影响之后提交的新任务”. Run:

`python3 -m pytest -q tests/test_webapp_app.py tests/test_webapp_render.py`

Expected: PASS.

- [ ] **Step 5: Commit the settings dialog**

```bash
git add webapp/templates/index.html tests/test_webapp_app.py
git commit -m "feat: add web model settings dialog"
```

---

### Task 9: Documentation, distribution and end-to-end verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `SKILL.md`
- Regenerate: `dist/openclaw/`
- Test: all existing and new tests

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented precedence rules and a verified running Web service.

- [ ] **Step 1: Update user documentation with exact precedence and security semantics**

Document these rules verbatim in the appropriate configuration sections:

```text
Web 工作台优先使用 webapp/_data/model-settings.json；文件不存在时从 .env/config.yaml 导入一次。
Web 设置只影响之后提交的新任务；CLI/OpenClaw 始终继续读取 .env/config.yaml。
API Key 仅保存在本机，但任何获得工作台登录密码的人都能在设置页面查看完整值。
Web 生图只调用当前选中的一个模型，失败时任务直接失败，不自动回退或生成占位图。
```

Update `.env.example` comments to identify variables as first-run bootstrap and CLI/OpenClaw settings after local Web settings exist. Update `SKILL.md` only for the Web boundary; do not change Agent direct-flow fallback instructions.

- [ ] **Step 2: Regenerate the OpenClaw distribution and inspect scope**

Run: `python3 scripts/build_openclaw.py`

Then run these commands separately:

```bash
git status --short
git diff --stat
git diff --check
```

Expected: only planned source, test, documentation and corresponding `dist/openclaw` files are modified. If the build surfaces a stale unrelated generated file, restore only that generated file's pre-task content without touching source or user changes.

- [ ] **Step 3: Run the full automated verification matrix**

Run:

```bash
python3 -m pytest -q
python3 -m compileall -q toolkit scripts webapp
docker compose config -q
```

Expected: pytest reports zero failures; compileall and Compose exit 0.

- [ ] **Step 4: Restart and verify the live service without paid calls**

Run:

```bash
docker compose restart wechat-studio-web
curl -fsS -m 5 http://127.0.0.1:9997/api/health
docker compose ps
```

Expected: health JSON contains `"ok": true`; container status is healthy. Log in and verify the settings modal loads current local values, toggles both key fields, changes tabs, and cancels without saving. Do not click either connection-test button during this no-cost smoke test.

- [ ] **Step 5: Hand off optional real connection tests for explicit user confirmation**

Ask the user to log in from their browser and click writing “测试连接”; verify the selected Provider/model and elapsed time appear. For “测试生图”, the user must personally accept the charge confirmation before the request is sent; no automated verification command may trigger a paid image. After the user performs either test, inspect container logs and confirm they contain only Provider/model/host metadata and neither complete API Key. Lack of a paid manual test does not block automated implementation verification.

- [ ] **Step 6: Commit documentation and generated distribution**

```bash
git add README.md .env.example SKILL.md dist/openclaw
git commit -m "docs: document web model settings"
```

- [ ] **Step 7: Final scope and secret audit**

Run:

```bash
git status --short
git diff --check HEAD~10..HEAD
git log -10 --oneline
```

Inspect staged and committed diffs for literal API keys, Authorization headers, `.env`, `model-settings.json`, test images and unrelated user files. Expected: no secret-bearing or runtime-generated file is tracked, and pre-existing unrelated working-tree changes remain intact.
