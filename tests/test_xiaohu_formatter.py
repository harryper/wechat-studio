import subprocess
from pathlib import Path
from types import SimpleNamespace

from toolkit import xiaohu_formatter


def test_format_article_removes_temporary_output(tmp_path, monkeypatch):
    monkeypatch.setattr(xiaohu_formatter.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(xiaohu_formatter.uuid, "uuid4", lambda: SimpleNamespace(hex="1234567890abcdef"))

    def fake_run(cmd, **kwargs):
        output_dir = Path(cmd[cmd.index("--output") + 1])
        input_stem = Path(cmd[cmd.index("--input") + 1]).stem
        article_dir = output_dir / input_stem
        article_dir.mkdir(parents=True)
        (article_dir / "article.html").write_text("<p>正文</p>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(xiaohu_formatter.subprocess, "run", fake_run)
    html = xiaohu_formatter.format_article("# 标题\n\n正文", "terracotta")
    assert html == "<p>正文</p>"
    assert not list(tmp_path.glob("wechat_studio_*.md"))
    assert not list(tmp_path.glob("wechat_studio_out_*"))
