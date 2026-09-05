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


def test_write_article_uses_edited_prompt_verbatim(monkeypatch):
    captured = capture_generate_text(monkeypatch)
    edited_prompt = "  用户在 Web 中编辑后的完整 Prompt\n"

    write_article.write_article(
        TOPIC,
        prompt=edited_prompt,
        settings=WRITING_SETTINGS,
    )

    assert captured["prompt"] == edited_prompt


@pytest.mark.parametrize(
    ("topic", "expected_headings"),
    [
        (
            {"title": "逆向思维", "category": "思维方法"},
            ["## 摘要", "## § 1 起源", "## § 2 发展演变", "## § 3 影响与应用", "## § 4 反直觉点"],
        ),
        (
            {"title": "复利的机制", "category": "经济学"},
            ["## 摘要", "## § 1 原理阐释", "## § 2 证据链", "## § 3 现代应用", "## § 4 局限与边界"],
        ),
        (
            {"title": "经典服从实验", "category": "心理学"},
            ["## 摘要", "## § 1 实验背景", "## § 2 实验设计", "## § 3 结果与争议", "## § 4 当代启示"],
        ),
    ],
)
def test_prompt_framework_keeps_length_constraints_out_of_headings(
    topic, expected_headings
):
    prompt = write_article._build_prompt(topic)
    headings = [line.strip() for line in prompt.splitlines() if line.strip().startswith("## ")]

    assert headings == expected_headings
    assert "约 100 字" in prompt
    assert "标题中不得出现字数、数量或结构说明" in prompt


def test_write_article_removes_copied_constraints_from_generated_headings(monkeypatch):
    generated = """# 逆向思维（从失败出发）

## 摘要（约 100 字）

摘要正文。

## § 1 起源（300-500 字）

第一节正文。

## § 2 证据链（3-4 个经典案例，共 800 字）

第二节正文。"""
    monkeypatch.setattr(write_article, "generate_text", lambda *args, **kwargs: generated)

    result = write_article.write_article(
        TOPIC,
        prompt="写作",
        settings=WRITING_SETTINGS,
    )

    assert result.startswith("# 逆向思维（从失败出发）")
    assert "## 摘要\n" in result
    assert "## § 1 起源\n" in result
    assert "## § 2 证据链\n" in result
    assert "约 100 字" not in result
    assert "300-500 字" not in result
    assert "3-4 个经典案例" not in result


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


def test_write_article_legacy_model_override_does_not_require_env_model(monkeypatch):
    monkeypatch.setattr(write_article.env_config, "_loaded", True)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://legacy.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "legacy-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    captured = capture_generate_text(monkeypatch)

    write_article.write_article(TOPIC, model="override")

    assert captured["settings"]["model"] == "override"


def test_write_article_model_override_does_not_mutate_settings(monkeypatch):
    captured = capture_generate_text(monkeypatch)

    write_article.write_article(TOPIC, settings=WRITING_SETTINGS, model="override")

    assert captured["settings"]["model"] == "override"
    assert WRITING_SETTINGS["model"] == "writer"
