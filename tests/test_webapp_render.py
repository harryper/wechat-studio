"""Tests for webapp/render.py _write_preview_html CJK-spacing defense.

These tests guard against the historical bug where a previous webapp version
went through converter.py's legacy path (which inserts U+0020 between every
CJK pair), polluting article.html files with `可 得性`-style spacing.

The defense: after cli.py preview writes article.html, scan it for the
CJK+CJK space pattern. If found, re-render via xiaohu directly so the
output is clean regardless of which path cli.py used.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from webapp import render


CJK_PAIR_RE = re.compile(r"[一-鿿] [一-鿿]")


def _make_workdir(tmp_path: Path, article_md: str) -> Path:
    wd = tmp_path / "workdir"
    wd.mkdir()
    (wd / "article.md").write_text(article_md, encoding="utf-8")
    return wd


def test_write_preview_html_drops_legacy_cjk_cjk_spacing(tmp_path, monkeypatch):
    """If cli.py preview somehow produces a CJK-spaced article.html,
    _write_preview_html must re-render via xiaohu so the final file is clean.
    """
    workdir = _make_workdir(tmp_path, "# 测试\n\n可得性启发。\n")

    bad_html = (
        "<!DOCTYPE html><html><head><style>body{margin:0;padding:0;background:#f5f5f5}</style></head>"
        "<body><p>可 得性 启发。</p></body></html>"
    )
    clean_inner = '<section><p>可得性启发。</p></section>'

    def fake_run(cmd, **kwargs):
        # First call: cli.py preview with -o OUTPUT (bad_html)
        if "-o" in cmd:
            out = cmd[cmd.index("-o") + 1]
            Path(out).write_text(bad_html, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        # Second call: xiaohu fallback writes preview.html inside <stem>/ dir
        if "--output" in cmd:
            xiaohu_out_dir = Path(cmd[cmd.index("--output") + 1])
            stem = Path(cmd[cmd.index("--input") + 1]).stem
            target_dir = xiaohu_out_dir / stem
            target_dir.mkdir(exist_ok=True)
            (target_dir / "preview.html").write_text(clean_inner, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    monkeypatch.setattr(render, "_write_preview_html", render._write_preview_html)

    render._write_preview_html(workdir, theme="terracotta")

    final = (workdir / "article.html").read_text(encoding="utf-8")
    assert not CJK_PAIR_RE.search(final), (
        f"CJK-CJK space pattern survived _write_preview_html: {final[:300]!r}"
    )


def test_write_preview_html_keeps_clean_output_intact(tmp_path, monkeypatch):
    """If cli.py preview already produces clean HTML, _write_preview_html
    must not touch it (no extra xiaohu round-trip).
    """
    workdir = _make_workdir(tmp_path, "# 测试\n\n可得性启发。\n")
    clean_html = (
        "<!DOCTYPE html><html><head></head>"
        "<body><p>可得性启发。</p></body></html>"
    )
    written = {}

    def fake_run(cmd, **kwargs):
        out = cmd[cmd.index("-o") + 1]
        Path(out).write_text(clean_html, encoding="utf-8")
        written["count"] = written.get("count", 0) + 1
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    render._write_preview_html(workdir, theme="terracotta")

    assert written.get("count", 0) == 1, "should not re-render when output is already clean"


def test_insert_images_adds_cover_and_four_inline_images():
    md = """# 标题

> **分类**：心理学

## 摘要

摘要。

## § 1 起源

正文。

## § 2 机制

正文。

## § 3 证据

正文。

## § 4 应用

正文。
"""
    rels = [f"images/inline-{i}.jpg" for i in range(1, 5)]
    result = render._insert_images(md, "images/cover.jpg", rels)
    assert result.count("![") == 5
    assert result.count("images/cover.jpg") == 1
    for rel in rels:
        assert result.count(rel) == 1


def test_generate_images_reports_mixed_mode(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    calls = []

    def fake_generate(prompt, output, size, **kwargs):
        calls.append(Path(output).name)
        if output.endswith("inline-2.jpg"):
            raise RuntimeError("quota")
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image", fake_generate)
    topic = {"id": "kb-001", "title": "测试", "category": "psychology", "key_points": ["a", "b"]}
    mode = render.generate_images_in_workdir(workdir, topic, render.default_image_rels())
    assert mode == "mixed"
    assert calls == ["cover.jpg", "inline-1.jpg", "inline-2.jpg", "inline-3.jpg", "inline-4.jpg"]
    states = __import__("json").loads((workdir / "image-status.json").read_text())
    assert states["inline-2"] == "placeholder"
    assert all((workdir / rel).is_file() for rel in render.default_image_rels())


def test_generate_images_accepts_every_successful_provider_result(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    calls = []

    def fake_generate(prompt, output, size):
        calls.append((prompt, Path(output).name, size))
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image", fake_generate)
    mode = render.generate_images_in_workdir(workdir, TOPIC, render.default_image_rels())

    assert mode == "real"
    assert len(calls) == 5
    states = json.loads((workdir / "image-status.json").read_text())
    assert set(states.values()) == {"real"}
    assert not (workdir / "image-diagnostics.json").exists()


TOPIC = {
    "id": "kb-001",
    "title": "幸存者偏差",
    "category": "认知偏差",
    "key_points": ["返航轰炸机的弹孔分布", "沉默的证据", "选择效应", "现代商业误用"],
}

def _all_prompts(topic):
    return [render._cover_prompt(topic), *render._inline_prompts(topic)]


def test_prompts_restore_educational_editorial_style_without_visible_text():
    for prompt in _all_prompts(TOPIC):
        assert "知识型编辑插画" in prompt
        assert "现代科普杂志视觉" in prompt
        assert "所有图形元素不加文字标签" in prompt
        assert "不得出现标题、段落、字母、汉字、数字、水印或logo" in prompt
        assert "电影感场景" not in prompt
        assert "单一视觉焦点" not in prompt


def test_cover_is_a_structured_conceptual_science_cover():
    prompt = render._cover_prompt(TOPIC)
    assert "结构化概念封面" in prompt
    assert "核心视觉隐喻" in prompt
    assert "概念关系清晰" in prompt
    assert "自然留白" in prompt


def test_inline_prompts_have_distinct_science_explanation_roles():
    prompts = render._inline_prompts(TOPIC)
    assert "历史重建式科普插画" in prompts[0]
    assert "无文字机制图解" in prompts[1]
    assert "无文字箭头、分层或路径" in prompts[1]
    assert "证据与实验型科普插画" in prompts[2]
    assert "应用与边界对照式科普插画" in prompts[3]


def test_prompts_keep_topic_semantics_as_visual_context():
    cover = render._cover_prompt(TOPIC)
    assert TOPIC["title"] in cover
    assert TOPIC["category"] in cover
    for point, prompt in zip(TOPIC["key_points"], render._inline_prompts(TOPIC)):
        assert point in prompt


def test_ensure_default_image_references_upgrades_legacy_article(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    legacy = """# 标题

> **分类**：心理学

![封面](images/cover.jpg)

## 摘要

摘要。

## § 1 起源

![配图](images/inline-1.jpg)

## § 2 机制

## § 3 证据

![配图](images/inline-2.jpg)

## § 4 应用
"""
    (workdir / "article.md").write_text(legacy, encoding="utf-8")
    render.ensure_default_image_references(workdir)
    upgraded = (workdir / "article.md").read_text(encoding="utf-8")
    assert upgraded.count("![") == 5
    for rel in render.default_image_rels():
        assert upgraded.count(rel) == 1
