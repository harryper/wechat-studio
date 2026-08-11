#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Article generation + image generation + preview rendering pipeline.

Replaces the structural mock in webapp/synthesize.py with a real pipeline:

    1. write_article()  — LLM (MiniMax via Anthropic-compatible API)
    2. generate_images() — image_gen.py (cover + 2 inline illustrations)
    3. cli.py preview  — render themed HTML

The workdir layout produced:
    {workdir}/
      article.md      — has relative image refs (images/cover.jpg, ...)
      article.html    — output of cli.py preview (not used directly here)
      images/
        cover.jpg
        inline-1.jpg
        inline-2.jpg

For the iframe srcdoc preview we re-write ``<img src="images/X.jpg">``
to ``<img src="data:image/jpeg;base64,...">`` so the images load without
a web server. cli.py publish keeps the relative paths, since it uploads
local files to WeChat and rewrites the URLs itself.

Strict mode: every failure raises — caller surfaces to user, no fallback.
"""

from __future__ import annotations

import base64
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make 'scripts.write_article' and 'image_gen' importable without packaging.
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"
SCRIPTS_DIR = SKILL_DIR / "scripts"

for p in (str(SKILL_DIR), str(TOOLKIT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.write_article import write_article  # type: ignore  # noqa: E402
from image_gen import generate_image  # type: ignore  # noqa: E402


log = logging.getLogger("wechat-studio.render")


# ── 提示词构造 ────────────────────────────────────────────────────────
def _key_points(topic: Dict[str, Any]) -> List[str]:
    return [p for p in (topic.get("key_points") or []) if p]


def _cover_prompt(topic: Dict[str, Any]) -> str:
    """Cover-image prompt — sets the article's visual identity."""
    title = (topic.get("title") or "").strip()
    category = (topic.get("category") or "").strip()
    kps = _key_points(topic)
    head = kps[0] if kps else title
    return (
        f"「{title}」概念插画，"
        f"{category}主题，"
        f"核心意象：{head}，"
        "学术插画风格，深色调，高质感构图，留白，不含文字"
    )


def _inline_prompts(topic: Dict[str, Any]) -> List[str]:
    """Inline-image prompts — one per major section after §1 and §3."""
    title = (topic.get("title") or "").strip()
    kps = _key_points(topic)
    fallback = title or "概念图示"
    return [
        (
            f"「{kps[1] if len(kps) >= 2 else kps[0] if kps else fallback}」"
            "经典场景示意，简洁线稿风格，浅色背景，无文字"
        ),
        (
            f"「{kps[2] if len(kps) >= 3 else kps[0] if kps else fallback}」"
            "现代应用示意，数据可视化风格，无文字"
        ),
    ]


# ── 图像插入位置 ──────────────────────────────────────────────────────
def _find_after_quote(lines: List[str]) -> Optional[int]:
    """Insert position right after the closing ``> ...`` quote block."""
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            return i + 2
    return None


def _find_before_section(lines: List[str], candidates: Tuple[str, ...]) -> Optional[int]:
    """Insert position just before the first matching section heading."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        for cand in candidates:
            if cand in stripped:
                return i
    return None


def _insert_images(md: str, cover_rel: str, inline_rels: List[str]) -> str:
    """Insert image references at sensible positions in the markdown."""
    lines = md.split("\n")
    inserts: List[Tuple[int, str]] = []

    cover_pos = _find_after_quote(lines)
    if cover_pos is not None:
        inserts.append((cover_pos, f"![封面]({cover_rel})"))

    inline1_pos = _find_before_section(lines, ("§ 2", "## § 3", "三、"))
    if inline1_pos is not None and inline_rels:
        inserts.append((inline1_pos, f"![配图]({inline_rels[0]})"))

    inline2_pos = _find_before_section(lines, ("§ 4", "## 反直觉", "四、", "局限"))
    if inline2_pos is not None and len(inline_rels) >= 2:
        inserts.append((inline2_pos, f"![配图]({inline_rels[1]})"))

    for pos, text in sorted(inserts, key=lambda x: -x[0]):
        lines.insert(pos, text)

    return "\n".join(lines)


# ── 步骤 1：写文章（仅 LLM，无图片）─────────────────────────────────────
def write_article_to_workdir(topic: Dict[str, Any]) -> Tuple[Path, List[str]]:
    """Write the article markdown into a fresh workdir.

    Returns ``(workdir, image_rels)`` — image_rels lists the relative
    paths that will be filled in by generate_images_in_workdir().
    """
    workdir = Path(tempfile.mkdtemp(prefix="ws-render-"))
    (workdir / "images").mkdir()

    md_text = write_article(topic)

    cover_rel = "images/cover.jpg"
    inline_rels = ["images/inline-1.jpg", "images/inline-2.jpg"]
    md_with_images = _insert_images(md_text, cover_rel, inline_rels)

    md_file = workdir / "article.md"
    md_file.write_text(md_with_images, encoding="utf-8")

    return workdir, [cover_rel, *inline_rels]


# ── 步骤 2：生成图片（image_gen 链）─────────────────────────────────────
def generate_images_in_workdir(
    workdir: Path,
    topic: Dict[str, Any],
    image_rels: List[str],
) -> None:
    """Generate the cover + inline images via toolkit/image_gen.py.

    The first provider in config.yaml's chain is tried first; on failure
    the next is used automatically. Raises the last error if all fail.
    """
    img_dir = workdir / "images"

    cover_rel = image_rels[0]
    inline_rels = image_rels[1:]

    log.info("generating cover image: %s", _cover_prompt(topic)[:60])
    generate_image(_cover_prompt(topic), str(img_dir / Path(cover_rel).name),
                    size="cover")

    for idx, rel in enumerate(inline_rels):
        prompt = _inline_prompts(topic)[idx] if idx < len(_inline_prompts(topic)) \
                 else _inline_prompts(topic)[0]
        log.info("generating inline image %d: %s", idx + 1, prompt[:60])
        generate_image(prompt, str(img_dir / Path(rel).name), size="article")


# ── 步骤 3：渲染预览（cli.py preview）──────────────────────────────────
def render_preview_html(workdir: Path, theme: str) -> str:
    """Run cli.py preview on article.md and return HTML with embedded data URIs."""
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
    html = html_file.read_text(encoding="utf-8")
    return _embed_images_as_data_uris(html, workdir)


# ── 把图片 src 替换成 data URI（给 iframe srcdoc 用）────────────────────
_IMG_TAG_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)("[^>]*>)', re.DOTALL)
_MIME_FOR_EX = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}


def _embed_images_as_data_uris(html: str, workdir: Path) -> str:
    """Replace local image srcs with base64 data URIs read from workdir."""

    def replace(match: re.Match) -> str:
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        if src.startswith(("data:", "http://", "https://", "file://")):
            return match.group(0)
        img_path = (workdir / src).resolve()
        if not img_path.is_file():
            log.warning("image not found for embedding: %s", img_path)
            return match.group(0)
        try:
            data = img_path.read_bytes()
        except OSError as e:
            log.warning("failed reading %s: %s", img_path, e)
            return match.group(0)
        ext = img_path.suffix.lstrip(".").lower() or "jpeg"
        mime = _MIME_FOR_EX.get(ext, "image/jpeg")
        b64 = base64.b64encode(data).decode("ascii")
        return f"{prefix}data:{mime};base64,{b64}{suffix}"

    return _IMG_TAG_RE.sub(replace, html)