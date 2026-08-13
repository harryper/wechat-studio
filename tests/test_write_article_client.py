from scripts import write_article


class _TextBlock:
    text = "# 测试标题\n\n正文"


class _Messages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("Response", (), {"content": [_TextBlock()]})()


class _LLMClient:
    def __init__(self):
        self.messages = _Messages()


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
    llm_client = _LLMClient()
    seen = {}

    monkeypatch.setattr(write_article, "_build_client", lambda: llm_client)

    def fake_build_prompt(topic, client=None):
        seen["client"] = client
        return "prompt"

    monkeypatch.setattr(write_article, "_build_prompt", fake_build_prompt)

    markdown = write_article.write_article(
        {"title": "测试主题"},
        client="demo",
    )

    assert seen["client"] == "demo"
    assert markdown.startswith("# 测试标题")
    assert llm_client.messages.kwargs["messages"][0]["content"] == "prompt"
