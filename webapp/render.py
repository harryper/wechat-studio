#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Article generation + preview rendering pipeline.

Replaces the structural mock in webapp/synthesize.py with a real
content pipeline:

    1. write_article()        — LLM (MiniMax via Anthropic-compatible API)
    2. cli.py preview         — render themed HTML

The workdir layout:
    {workdir}/
      article.md       — output of write_article (no image refs)
      article.html     — output of cli.py preview

Strict mode: every failure raises — caller surfaces to user, no fallback.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

# Make 'scripts.write_article' importable without packaging.
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"

for p in (str(SKILL_DIR), str(TOOLKIT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.write_article import write_article  # type: ignore  # noqa: E402

log = logging.getLogger("wechat-studio.render")


# ── 步骤 1：写文章（仅 LLM，无图片）─────────────────────────────────────
def write_article_to_workdir(topic: Dict[str, Any]) -> Tuple[Path, str]:
    """Write the article markdown into a fresh workdir.

    Returns ``(workdir, md_text)``. cli.py publish later uses the workdir
    to resolve relative paths, so callers should keep it alive until publish.
    """
    workdir = Path(tempfile.mkdtemp(prefix="ws-render-"))

    md_text = write_article(topic)

    md_file = workdir / "article.md"
    md_file.write_text(md_text, encoding="utf-8")
    return workdir, md_text


# ── 步骤 2：渲染预览（cli.py preview）──────────────────────────────────
def render_preview_html(workdir: Path, theme: str) -> str:
    """Run cli.py preview on article.md and return the themed HTML."""
    md_file = workdir / "article.md"
    html_file = workdir / "article.html"

    proc = subprocess.run(
        [
            sys.executable,
            str(TOOLKIT_DIR / "cli.py"),
            "preview",
            str(md_file),
            "--theme",
            theme,
            "--no-open",
            "-o",
            str(html_file),
        ],
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not html_file.exists():
        raise RuntimeError(
            f"cli.py preview 失败 (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return html_file.read_text(encoding="utf-8")