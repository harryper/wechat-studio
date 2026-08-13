import sys
from pathlib import Path
from types import SimpleNamespace

# toolkit/cli.py uses bare imports like `from converter import ...` which
# only resolve when the toolkit directory itself is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "toolkit"))

import pytest
from toolkit.cli import (
    DISCLAIMER,
    _find_cover_source,
    _strip_publish_metadata,
    cmd_publish,
    inject_disclaimer,
)


def test_inject_disclaimer_appends():
    md = "# 幸存者偏差\n\n正文内容"
    out = inject_disclaimer(md)
    assert "本文为逻辑梳理" in out
    assert "非学术研究" in out


def test_inject_disclaimer_idempotent():
    md = "# 幸存者偏差\n\n正文\n\n" + DISCLAIMER.strip()
    out = inject_disclaimer(md)
    assert out.count("本文为逻辑梳理") == 1


def test_inject_disclaimer_preserves_frontmatter():
    md = "---\ntitle: foo\n---\n\n# 标题\n\n正文"
    out = inject_disclaimer(md)
    # Disclaimer goes after content, before frontmatter stays
    assert out.startswith("---\n")
    assert "本文为逻辑梳理" in out


def test_strip_publish_metadata_starts_at_first_h2():
    md = """# 文章标题

> **分类**：心理学　　**主题 ID**：`kb-001`

![封面](images/cover.jpg)

## 摘要

摘要正文。

![配图](images/inline-1.jpg)
"""
    body = _strip_publish_metadata(md)
    assert body.startswith("## 摘要")
    assert "# 文章标题" not in body
    assert "**分类**" not in body
    assert "images/cover.jpg" not in body
    assert "images/inline-1.jpg" in body


def test_strip_publish_metadata_keeps_markdown_without_h2():
    md = "# 标题\n\n只有一段正文"
    assert _strip_publish_metadata(md) == md


@pytest.mark.parametrize(
    ("images", "expected"),
    [
        (["images/inline.jpg", "images/cover.jpg"], "images/cover.jpg"),
        (["cover.PNG"], "cover.PNG"),
        ([r"images\\cover.webp"], r"images\\cover.webp"),
        (["https://cdn.example/cover.jpeg?x=1"], "https://cdn.example/cover.jpeg?x=1"),
        (["images/discover.png", "images/cover.svg"], None),
    ],
)
def test_find_cover_source(images, expected):
    assert _find_cover_source(images) == expected


def test_publish_strips_metadata_and_auto_detects_cover(tmp_path, monkeypatch):
    md_path = tmp_path / "article.md"
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "cover.jpg").write_bytes(b"cover")
    (tmp_path / "images" / "inline-1.jpg").write_bytes(b"inline")
    md_path.write_text(
        "# 文章标题\n\n"
        "> **分类**：心理学\n\n"
        "![封面](images/cover.jpg)\n\n"
        "## 摘要\n\n摘要正文。\n\n"
        "![配图](images/inline-1.jpg)\n",
        encoding="utf-8",
    )

    converted = {}
    uploaded_body = []
    draft_args = {}

    class FakeConverter:
        def __init__(self, theme):
            pass

        def convert(self, markdown):
            converted["markdown"] = markdown
            return SimpleNamespace(
                html='<p>摘要正文。</p><img src="images/inline-1.jpg">',
                title="",
                digest="",
            )

    monkeypatch.setattr("toolkit.cli.load_config", lambda: {
        "wechat": {"appid": "appid", "secret": "secret"}
    })
    monkeypatch.setattr("toolkit.cli.list_xiaohu_themes", lambda: [])
    monkeypatch.setattr("toolkit.cli.load_theme", lambda name: object())
    monkeypatch.setattr("toolkit.cli.WeChatConverter", FakeConverter)
    monkeypatch.setattr("toolkit.cli.get_access_token", lambda appid, secret: "token")
    monkeypatch.setattr(
        "toolkit.cli.upload_image",
        lambda token, path: uploaded_body.append(Path(path).name) or "https://wechat/inline",
    )
    monkeypatch.setattr(
        "toolkit.cli.upload_thumb",
        lambda token, path: "thumb:" + Path(path).name,
    )

    def fake_create_draft(**kwargs):
        draft_args.update(kwargs)
        return SimpleNamespace(media_id="draft-id")

    monkeypatch.setattr("toolkit.cli.create_draft", fake_create_draft)

    args = SimpleNamespace(
        input=str(md_path), appid=None, secret=None, theme="professional-clean",
        author=None, cover=None, title=None, digest=None,
    )
    cmd_publish(args)

    assert converted["markdown"].startswith("## 摘要")
    assert "# 文章标题" not in converted["markdown"]
    assert "**分类**" not in converted["markdown"]
    assert "images/cover.jpg" not in converted["markdown"]
    assert uploaded_body == ["inline-1.jpg"]
    assert draft_args["title"] == "文章标题"
    assert draft_args["thumb_media_id"] == "thumb:cover.jpg"
    assert "https://wechat/inline" in draft_args["html"]
