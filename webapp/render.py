#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Article generation + image generation + preview rendering pipeline.

Three-step pipeline that replaces the structural mock in
webapp/synthesize.py with real content:

    1. write_article()        — LLM (MiniMax via Anthropic-compatible API)
    2. generate_images()      — image_gen.py with PIL placeholder fallback
    3. cli.py preview         — render themed HTML

The workdir layout:
    {workdir}/
      article.md
      article.html
      images/
        cover.jpg
        inline-1.jpg ... inline-4.jpg

The iframe loads ``article.html`` directly from the workdir via
``/api/history/<id>/html`` (relative ``<img src="images/X.jpg">`` paths
resolve against the iframe's base URL to ``/api/history/<id>/images/...``).
cli.py publish keeps the relative paths, since it uploads local files
to WeChat and rewrites the URLs itself.

Image strategy: try the configured AI providers (MiniMax / OpenAI —
whichever has quota + key) in order. If every provider fails,
fall back to locally-generated placeholder images via PIL — deterministic
color blocks with the topic title baked in via Pillow's default font.
This keeps the WYSIWYG preview usable in environments where no AI image
provider is configured.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make 'scripts.write_article' and 'image_gen' importable without packaging.
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"

for p in (str(SKILL_DIR), str(TOOLKIT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.write_article import write_article  # type: ignore  # noqa: E402
from image_gen import generate_image  # type: ignore  # noqa: E402

log = logging.getLogger("wechat-studio.render")


# ── workdir 路径 ──────────────────────────────────────────────────────
# Web UI 把 workdir 放在 bind-mount 的 webapp/_data/ 下，这样 gunicorn
# worker 回收、容器重启都不会丢 workdir → publish 总是能跑到 article.md。
# history.py 会按 history id 给每个 workdir 一个稳定名字。
WORKDIR_ROOT = Path(__file__).resolve().parent / "_data" / "workdirs"


# ── 提示词构造 ────────────────────────────────────────────────────────
# 图片服务会把提示词里被引号/书名号包裹的字符串当成"要画上去的文字"，
# 所以运行时提示词不引用标题，只把主题描述成视觉语义，再统一追加中英
# 双语硬约束。英文那半句是给以英文训练为主的模型看的，缺了它 MiniMax
# 仍会渲染出伪拉丁字符。
_NO_TEXT_CONSTRAINT = (
    "纯视觉插画；画面中不得出现任何标题、段落、字母、汉字、数字、标签、"
    "图例、水印、logo、标牌、书页、屏幕界面、图表或海报排版。"
    "purely pictorial illustration, no text, no letters, no words, no numbers, "
    "no captions, no labels, no watermark, no logo, no signage, no book pages, "
    "no UI screens, no charts, no poster layout"
)

_QUOTE_CHARS = "「」『』《》【】〈〉“”‘’\"'"


def _pictorial_subject(text: str) -> str:
    """Strip typographic quoting so the text reads as a scene, not a string."""
    return "".join(ch for ch in (text or "") if ch not in _QUOTE_CHARS).strip()


def _key_points(topic: Dict[str, Any]) -> List[str]:
    return [p for p in (topic.get("key_points") or []) if p]


def _cover_prompt(topic: Dict[str, Any]) -> str:
    """Cover-image prompt — sets the article's visual identity."""
    title = _pictorial_subject(topic.get("title") or "")
    category = _pictorial_subject(topic.get("category") or "")
    kps = [_pictorial_subject(p) for p in _key_points(topic)]
    head = kps[0] if kps else title
    return (
        f"一幅具体的编辑插画，主题领域是{category}，"
        f"表现的概念是{title}，"
        f"核心视觉意象：{head}，"
        "学术插画风格，深色调，高质感构图，一侧保留干净留白（留白处同样不得有文字），"
        f"{_NO_TEXT_CONSTRAINT}"
    )


def _inline_prompts(topic: Dict[str, Any]) -> List[str]:
    """Build four complementary prompts for the article's major sections."""
    title = _pictorial_subject(topic.get("title") or "")
    kps = [_pictorial_subject(p) for p in _key_points(topic)]
    fallback = title or "抽象概念场景"
    treatments = [
        "起源或经典场景的具体瞬间，简洁线稿，浅色背景",
        "核心机制的具体物象隐喻，层次清晰，低饱和度",
        "关键证据或实验现场，纪实学术插画",
        "现代应用与边界的视觉隐喻，编辑感构图",
    ]
    return [
        (
            f"一幅具体的编辑插画，围绕{kps[i] if i < len(kps) else kps[-1] if kps else fallback}，"
            f"{treatment}，{_NO_TEXT_CONSTRAINT}"
        )
        for i, treatment in enumerate(treatments)
    ]


# ── PIL 占位图（AI provider 全失败时用）────────────────────────────────
def _placeholder_image(topic: Dict[str, Any], role: str) -> bytes:
    """Generate a deterministic placeholder JPEG.

    ``role`` is "cover" or one of "inline-1" ... "inline-4".

    The placeholder text is ASCII-only (topic id + category) because the
    container ships without CJK fonts and PIL's default bitmap font
    renders Chinese as tofu. Configure an image provider in config.yaml
    to get real (topical, multilingual) AI-generated artwork.
    """
    from PIL import Image, ImageDraw, ImageFont

    if role == "cover":
        size = (1024, 512)
        bg = (24, 28, 36)
        fg = (220, 224, 232)
        accent = (255, 77, 109)
    elif role in {"inline-1", "inline-3"}:
        size = (800, 450)
        bg = (244, 240, 232)
        fg = (62, 50, 40)
        accent = (180, 100, 60)
    else:
        size = (800, 450)
        bg = (234, 240, 246)
        fg = (40, 56, 72)
        accent = (60, 130, 180)

    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)

    # diagonal accent stripe for visual texture
    for offset in range(-size[1], size[0], 24):
        draw.line([(offset, 0), (offset + size[1], size[1])], fill=accent, width=2)

    topic_id = (topic.get("id") or "").strip()
    category = (topic.get("category") or "").strip()
    role_label = "PLACEHOLDER COVER" if role == "cover" else "PLACEHOLDER"

    # Try a few common font paths; fall back to PIL default bitmap font.
    def _font(size: int):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
        return ImageFont.load_default()

    big = _font(56 if role == "cover" else 36)
    small = _font(28 if role == "cover" else 22)

    def _draw_centered(text: str, y_frac: float, font, color) -> None:
        if not text:
            return
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = max(0, (size[0] - w) // 2)
        y = int(size[1] * y_frac - h / 2)
        draw.text((x, y), text, fill=color, font=font)

    _draw_centered(role_label, 0.36, big, accent if role == "cover" else fg)
    if topic_id:
        _draw_centered(topic_id, 0.56, big, fg)
    if category:
        _draw_centered(category, 0.74, small, accent if role != "cover" else fg)
    if role == "cover":
        _draw_centered("configure image api key for real art", 0.88, small, fg)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


# ── 图像插入位置 ──────────────────────────────────────────────────────
def _find_after_quote(lines: List[str]) -> Optional[int]:
    """Insert position right after the closing ``> ...`` quote block."""
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            return i + 2
    return None


def _insert_images(md: str, cover_rel: str, inline_rels: List[str]) -> str:
    """Insert image references at sensible positions in the markdown."""
    lines = md.split("\n")
    inserts: List[Tuple[int, str]] = []

    cover_pos = _find_after_quote(lines)
    if cover_pos is None:
        cover_pos = next((i + 2 for i, line in enumerate(lines) if line.startswith("# ")), 0)
    inserts.append((cover_pos, f"![封面]({cover_rel})"))

    headings = [
        i for i, line in enumerate(lines)
        if line.strip().startswith("## ") and "摘要" not in line
    ]
    for pos, rel in zip(headings[:4], inline_rels):
        inserts.append((pos, f"![配图]({rel})"))

    for pos, text in sorted(inserts, key=lambda x: -x[0]):
        lines.insert(pos, text)

    return "\n".join(lines)


# ── 步骤 1：写文章（仅 LLM，无图片）─────────────────────────────────────
def default_image_rels() -> List[str]:
    return ["images/cover.jpg", *[f"images/inline-{i}.jpg" for i in range(1, 5)]]


def ensure_default_image_references(workdir: Path) -> List[str]:
    """Upgrade an existing article to the current cover + four-inline layout."""
    md_path = workdir / "article.md"
    markdown = md_path.read_text(encoding="utf-8")
    rels = default_image_rels()
    if all(rel in markdown for rel in rels):
        return rels
    default_set = set(rels)
    lines = [
        line for line in markdown.splitlines()
        if not (
            line.strip().startswith("![")
            and any(f"]({rel})" in line for rel in default_set)
        )
    ]
    upgraded = _insert_images("\n".join(lines), rels[0], rels[1:])
    md_path.write_text(upgraded.rstrip() + "\n", encoding="utf-8")
    return rels


def write_article_to_workdir(
    topic: Dict[str, Any],
    workdir: Optional[Path] = None,
    client: Optional[str] = None,
) -> Tuple[Path, List[str]]:
    """Write the article markdown into a workdir.

    If ``workdir`` is None, creates a fresh one under WORKDIR_ROOT. Otherwise
    reuses the given path (used by history re-publish from an existing entry).

    Returns ``(workdir, image_rels)`` — image_rels lists the relative
    paths that will be filled in by generate_images_in_workdir().
    """
    if workdir is None:
        WORKDIR_ROOT.mkdir(parents=True, exist_ok=True)
        workdir = WORKDIR_ROOT / uuid.uuid4().hex
        workdir.mkdir()
    (workdir / "images").mkdir(exist_ok=True)

    md_text = write_article(topic, client=client)

    cover_rel = "images/cover.jpg"
    inline_rels = [f"images/inline-{i}.jpg" for i in range(1, 5)]
    md_with_images = _insert_images(md_text, cover_rel, inline_rels)

    md_file = workdir / "article.md"
    md_file.write_text(md_with_images, encoding="utf-8")

    return workdir, [cover_rel, *inline_rels]


# ── 步骤 2：生成图片（AI 链 + PIL 占位图 fallback）──────────────────────
def generate_images_in_workdir(
    workdir: Path,
    topic: Dict[str, Any],
    image_rels: List[str],
) -> str:
    """Generate one cover and four inline images.

    Tries the configured AI providers (image_gen.generate_image). If every
    provider fails — usually because no API key is configured or quota is
    exhausted — falls back to local PIL placeholder images so the preview
    still has visual structure. Returns ``"real"``, ``"mixed"``, or
    ``"placeholder"`` so the UI can report the aggregate mode accurately.
    """
    img_dir = workdir / "images"
    img_dir.mkdir(exist_ok=True)

    roles = ["cover", *[f"inline-{i}" for i in range(1, 5)]]
    prompts = [_cover_prompt(topic), *_inline_prompts(topic)]

    ai_failed: List[str] = []
    image_states: Dict[str, str] = {}
    for rel, role, prompt in zip(image_rels, roles, prompts):
        target = img_dir / Path(rel).name
        try:
            generate_image(prompt, str(target), size="cover" if role == "cover" else "article")
            image_states[role] = "real"
            continue
        except Exception as e:
            ai_failed.append(f"{role}: {type(e).__name__}: {e}")
            log.warning("AI image gen failed for %s: %s", role, e)
            # Drop a placeholder so the file always exists for cli.py preview / publish.
            target.write_bytes(_placeholder_image(topic, role))
            image_states[role] = "placeholder"

    (workdir / "image-status.json").write_text(
        json.dumps(image_states, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if ai_failed:
        log.warning("some AI images failed; using PIL placeholders. errors=%s",
                    "; ".join(ai_failed)[:400])
        return "placeholder" if len(ai_failed) == len(roles) else "mixed"
    return "real"


def generate_single_image_in_workdir(workdir: Path, topic: Dict[str, Any], role: str) -> str:
    """Regenerate one image and return the aggregate image mode."""
    roles = ["cover", *[f"inline-{i}" for i in range(1, 5)]]
    if role not in roles:
        raise ValueError(f"不支持的图片位置：{role}")
    prompts = dict(zip(roles, [_cover_prompt(topic), *_inline_prompts(topic)]))
    target = workdir / "images" / f"{role}.jpg"
    state_path = workdir / "image-status.json"
    try:
        states = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        states = {}
    try:
        generate_image(prompts[role], str(target), size="cover" if role == "cover" else "article")
        states[role] = "real"
    except Exception as e:
        log.warning("AI image regeneration failed for %s: %s", role, e)
        target.write_bytes(_placeholder_image(topic, role))
        states[role] = "placeholder"
    state_path.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")
    values = [states.get(item, "placeholder") for item in roles]
    if all(value == "real" for value in values):
        return "real"
    if all(value == "placeholder" for value in values):
        return "placeholder"
    return "mixed"


# ── 步骤 3：渲染预览（cli.py preview）──────────────────────────────────
def _write_preview_html(workdir: Path, theme: str) -> None:
    """Run cli.py preview on article.md, producing article.html in workdir.

    The iframe loads this directly via /api/history/<id>/html, so we don't
    return the HTML — we just need to make sure the file exists.
    """
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

    # Defensive: if cli.py ever dispatches to the legacy converter path
    # (converter.py `_fix_cjk_spacing` inserts U+0020 between every CJK pair),
    # the output article.html will read `可 得性` instead of `可得性`.
    # Detect that and overwrite with a clean xiaohu-rendered version.
    if re.search(r"[一-鿿] [一-鿿]", html_file.read_text(encoding="utf-8")):
        xiaohu_py = TOOLKIT_DIR.parent.parent / "xiaohu-wechat-format" / "scripts" / "format.py"
        rerun = subprocess.run(
            [
                sys.executable, str(xiaohu_py),
                "--input", str(md_file),
                "--theme", theme,
                "--format", "wechat",
                "--no-open",
                "--output", str(html_file.parent),
            ],
            cwd=str(SKILL_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        xiaohu_out = html_file.parent / md_file.stem / "preview.html"
        try:
            if rerun.returncode != 0 or not xiaohu_out.exists():
                raise RuntimeError(
                    f"xiaohu fallback 失败 (rc={rerun.returncode}): "
                    f"{(rerun.stderr or rerun.stdout).strip()}"
                )
            # xiaohu writes `<stem>/preview.html` inside the parent dir; move it
            # to article.html so the iframe loader finds it.
            xiaohu_html = xiaohu_out.read_text(encoding="utf-8")
            wrapped = (
                '<!DOCTYPE html><html lang="zh-CN"><head>'
                '<meta charset="UTF-8"><title>Preview</title>'
                '<style>body{margin:0;padding:0;background:#f5f5f5}</style>'
                '</head><body>' + xiaohu_html + '</body></html>'
            )
            html_file.write_text(wrapped, encoding="utf-8")
        finally:
            shutil.rmtree(xiaohu_out.parent, ignore_errors=True)


# xiaohu-wechat-format 的 preview 只输出 body { max-width, ... } 一段，
# 不带 img / 列表 / 表格等元素的样式 — 1024px 的 AI 封面图会按原尺寸渲染
# 撑爆 iframe。给 webapp 这一路的预览补一段基础阅读样式。
_IFRAME_BOOTSTRAP_CSS = """\
<style data-ws-bootstrap>
  body { word-wrap: break-word; overflow-wrap: break-word; }
  img { max-width: 100%; height: auto; display: block; margin: 16px auto; border-radius: 6px; }
  pre { white-space: pre-wrap; word-wrap: break-word; }
  table { max-width: 100%; }
  .preview-frame { max-width: 100%; }
</style>"""


def _inject_iframe_bootstrap(html: str) -> str:
    """Inject base reading CSS into the iframe HTML head.

    Targets the xiaohu preview path which emits only a body style block.
    Idempotent — if ``data-ws-bootstrap`` is already there, skip.
    """
    if 'data-ws-bootstrap' in html:
        return html
    if "</head>" in html:
        return html.replace("</head>", _IFRAME_BOOTSTRAP_CSS + "</head>", 1)
    # Fallback: prepend a head if missing entirely.
    return f"<head>{_IFRAME_BOOTSTRAP_CSS}</head>{html}"
