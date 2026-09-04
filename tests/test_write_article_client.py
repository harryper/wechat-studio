import pytest

from scripts import write_article


TOPIC = {
    "title": "损失厌恶",
    "category": "认知偏差",
    "key_points": ["损失比同额收益更显著"],
}
WRITING_SETTINGS = {
    "provider_id": "custom-openai",
    "adapter": "openai_compatible",
    "model": "writer",
    "base_url": "https://llm.example/v1",
    "api_key": "write-secret",
}
ARTICLE = "# 新标题\n\n## 摘要\n\n正文"


def capture_generate_text(monkeypatch):
    captured = {}

    def fake_generate(prompt, settings, **kwargs):
        captured.update(prompt=prompt, settings=settings, kwargs=kwargs)
        return ARTICLE

    monkeypatch.setattr(write_article, "generate_text", fake_generate)
    return captured


def test_build_client_requires_explicit_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(write_article.env_config, "SKILL_DIR", tmp_path)
    monkeypatch.setattr(write_article.env_config, "_loaded", False)
    monkeypatch.chdir(tmp_path)
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(write_article.env_config.ConfigError) as excinfo:
        write_article._build_client()

    assert "ANTHROPIC_BASE_URL" in str(excinfo.value)


def test_build_client_passes_api_key_to_sdk(monkeypatch):
    monkeypatch.setattr(write_article.env_config, "_loaded", True)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.test/anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    captured = {}

    def fake_anthropic(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(write_article.anthropic, "Anthropic", fake_anthropic)

    write_article._build_client()

    assert captured["base_url"] == "https://example.test/anthropic"
    assert captured["api_key"] == "test-key"
    assert "auth_token" not in captured


def test_client_context_loads_style_and_playbook(tmp_path, monkeypatch):
    client_dir = tmp_path / "clients" / "demo"
    client_dir.mkdir(parents=True)
    (client_dir / "style.yaml").write_text("tone: warm\nblacklist: [震惊]\n", encoding="utf-8")
    (client_dir / "playbook.md").write_text("不使用反问句。", encoding="utf-8")
    monkeypatch.setattr(write_article, "SKILL_DIR", tmp_path)
    context = write_article._load_client_context("demo")
    assert "tone: warm" in context
    assert "不使用反问句" in context


def test_client_context_rejects_path_traversal():
    try:
        write_article._load_client_context("../secret")
    except RuntimeError as exc:
        assert "客户名" in str(exc)
    else:
        raise AssertionError("path traversal client name should fail")


def test_write_article_keeps_customer_name_separate_from_llm_client(monkeypatch):
    seen = {}

    def fake_build_prompt(topic, client=None):
        seen["client"] = client
        return "prompt"

    monkeypatch.setattr(write_article, "_build_prompt", fake_build_prompt)
    captured = capture_generate_text(monkeypatch)

    markdown = write_article.write_article(
        {"title": "测试主题"},
        client="demo",
        settings=WRITING_SETTINGS,
    )

    assert seen["client"] == "demo"
    assert markdown.startswith("# 新标题")
    assert captured["prompt"] == "prompt"


def test_write_article_uses_runtime_settings(monkeypatch):
    captured = capture_generate_text(monkeypatch)

    result = write_article.write_article(
        TOPIC, settings=WRITING_SETTINGS, max_tokens=777, timeout=12
    )

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


def test_write_article_model_override_does_not_mutate_settings(monkeypatch):
    captured = capture_generate_text(monkeypatch)

    write_article.write_article(TOPIC, settings=WRITING_SETTINGS, model="override")

    assert captured["settings"]["model"] == "override"
    assert WRITING_SETTINGS["model"] == "writer"
