from scripts import write_article


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
