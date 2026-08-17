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


def test_generate_images_passes_local_validation_and_two_attempts(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    seen = []

    def fake_generate(prompt, output, size, **kwargs):
        seen.append(kwargs)
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image", fake_generate)
    render.generate_images_in_workdir(workdir, TOPIC, render.default_image_rels())

    assert len(seen) == 5
    for kwargs in seen:
        assert kwargs["validator"] is render.detect_text
        assert kwargs["attempts_per_provider"] == 2


def test_generate_images_writes_safe_diagnostics_for_all_roles(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)

    def fake_generate(prompt, output, size, **kwargs):
        if output.endswith("inline-2.jpg"):
            raise RuntimeError("quota")
        kwargs["diagnostics"].update({
            "provider": "minimax",
            "attempts": 2,
            "validation": "pass",
            "rejections": ["minimax attempt 1: detected 30 confident characters"],
        })
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image", fake_generate)
    render.generate_images_in_workdir(workdir, TOPIC, render.default_image_rels())

    diagnostics = json.loads((workdir / "image-diagnostics.json").read_text(encoding="utf-8"))
    assert set(diagnostics) == {"cover", "inline-1", "inline-2", "inline-3", "inline-4"}
    assert diagnostics["cover"]["provider"] == "minimax"
    assert diagnostics["cover"]["attempts"] == 2
    assert diagnostics["cover"]["validation"] == "pass"
    assert diagnostics["inline-2"]["validation"] == "failed"
    for entry in diagnostics.values():
        assert set(entry) <= {"provider", "attempts", "validation", "rejections"}
    blob = (workdir / "image-diagnostics.json").read_text(encoding="utf-8")
    for point in TOPIC["key_points"]:
        assert point not in blob
    assert "api_key" not in blob.lower()


def test_generate_single_image_passes_validation_and_records_diagnostics(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "image-status.json").write_text(
        json.dumps({role: "real" for role in
                    ["cover", "inline-1", "inline-2", "inline-3", "inline-4"]}),
        encoding="utf-8",
    )
    seen = []

    def fake_generate(prompt, output, size, **kwargs):
        seen.append(kwargs)
        kwargs["diagnostics"].update({
            "provider": "minimax", "attempts": 1,
            "validation": "not_available", "rejections": [],
        })
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image", fake_generate)
    mode = render.generate_single_image_in_workdir(workdir, TOPIC, "inline-3")

    assert mode == "real"
    assert seen[0]["validator"] is render.detect_text
    assert seen[0]["attempts_per_provider"] == 2
    diagnostics = json.loads((workdir / "image-diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["inline-3"]["validation"] == "not_available"


TOPIC = {
    "id": "kb-001",
    "title": "幸存者偏差",
    "category": "认知偏差",
    "key_points": ["返航轰炸机的弹孔分布", "沉默的证据", "选择效应", "现代商业误用"],
}

FORBIDDEN_SUBJECTS = ["标签", "图例", "水印", "logo", "标牌", "书页", "屏幕界面", "海报排版", "图表"]


def _all_prompts(topic):
    return [render._cover_prompt(topic), *render._inline_prompts(topic)]


def test_prompts_never_quote_the_title_with_book_brackets():
    for prompt in _all_prompts(TOPIC):
        assert "「" not in prompt and "」" not in prompt, prompt


def test_prompts_carry_the_english_hard_no_text_constraint():
    for prompt in _all_prompts(TOPIC):
        assert "no text, no letters, no words, no numbers" in prompt, prompt


def test_prompts_forbid_labels_logos_watermarks_and_poster_layouts():
    for prompt in _all_prompts(TOPIC):
        lowered = prompt.lower()
        for banned in FORBIDDEN_SUBJECTS:
            assert banned.lower() in lowered, f"missing ban on {banned}: {prompt}"


def test_prompts_keep_the_topic_as_visual_semantic_context():
    cover = render._cover_prompt(TOPIC)
    assert "认知偏差" in cover
    assert "返航轰炸机的弹孔分布" in cover
    inline = render._inline_prompts(TOPIC)
    assert len(inline) == 4
    for point, prompt in zip(TOPIC["key_points"], inline):
        assert point in prompt


def test_cover_prompt_keeps_clean_negative_space_without_text():
    cover = render._cover_prompt(TOPIC)
    assert "留白" in cover
    assert "no text, no letters, no words, no numbers" in cover


def test_prompts_avoid_text_inducing_composition_words():
    for prompt in _all_prompts(TOPIC):
        for lure in ["信息图", "流程图", "时间线", "学术海报", "数据图表", "infographic", "diagram"]:
            assert lure not in prompt, f"{lure} leaks into prompt: {prompt}"


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
