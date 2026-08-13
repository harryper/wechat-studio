"""Tests for webapp/render.py _write_preview_html CJK-spacing defense.

These tests guard against the historical bug where a previous webapp version
went through converter.py's legacy path (which inserts U+0020 between every
CJK pair), polluting article.html files with `可 得性`-style spacing.

The defense: after cli.py preview writes article.html, scan it for the
CJK+CJK space pattern. If found, re-render via xiaohu directly so the
output is clean regardless of which path cli.py used.
"""
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