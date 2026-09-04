#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Article generation + image generation + preview rendering pipeline.

Three-step pipeline that replaces the structural mock in
webapp/synthesize.py with real content:

    1. write_article()        — LLM (MiniMax via Anthropic-compatible API)
    2. generate_images()      — image_gen.py through the selected provider
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

Image strategy: Web jobs use the image provider explicitly chosen in model
settings. Image failures are surfaced to the job rather than silently filling
the preview with placeholder artwork.
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
from typing import Any, Dict, List, Literal, Optional, Tuple

# Make 'scripts.write_article' and 'image_gen' importable without packaging.
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"

for p in (str(SKILL_DIR), str(TOOLKIT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.write_article import write_article  # type: ignore  # noqa: E402
from image_gen import generate_image_with_provider  # type: ignore  # noqa: E402

log = logging.getLogger("wechat-studio.render")


# ── workdir 路径 ──────────────────────────────────────────────────────
# Web UI 把 workdir 放在 bind-mount 的 webapp/_data/ 下，这样 gunicorn
# worker 回收、容器重启都不会丢 workdir → publish 总是能跑到 article.md。
# history.py 会按 history id 给每个 workdir 一个稳定名字。
WORKDIR_ROOT = Path(__file__).resolve().parent / "_data" / "workdirs"


# ── 提示词构造 ────────────────────────────────────────────────────────
# GPT Image 2 can follow a grounded scene brief and render short labels reliably
# enough for editorial illustrations.  Put article evidence before aesthetics,
# keep one visual system across all five images, and only permit exact source
# labels so the model does not invent facts or poster copy.
_KNOWLEDGE_STYLE = (
    "当代科普编辑插画，横版16:9，2.5D扁平半写实。"
    "全篇统一视觉系统：低饱和海军蓝、赭石与暖象牙色，"
    "自然人物比例，中等粗细轮廓，克制材质细节与柔和环境光。"
)

_COMPOSITION_CONSTRAINT = (
    "画面只由一个连续的具体场景构成，最多两个人、最多四个关键物件。"
    "主体、关键动作和对比关系一眼可辨；背景简洁，同时保留正文提到的真实环境锚点。"
)

_COVER_COMPOSITION_CONSTRAINT = (
    "画面只由一个连续的具体场景构成，最多两个人、最多四个关键物件。"
    "使用清晰的封面视觉层级，主体、关键动作和对比关系一眼可辨，"
    "构图完整饱满，短标签服从画面而不是占据画面。"
)

_CONTENT_GROUNDING = (
    "只使用内容依据中明确出现的实体、动作和环境，至少呈现三个可从正文直接追溯的视觉锚点；"
    "不添加与正文无关的装饰性人物、物件、建筑或科研道具。"
)

_QUOTE_CHARS = "「」『』《》【】〈〉“”‘’\"'"


def _pictorial_subject(text: str) -> str:
    """Strip typographic quoting so the text reads as a scene, not a string."""
    return "".join(ch for ch in (text or "") if ch not in _QUOTE_CHARS).strip()


def _section_heading(text: str) -> str:
    """Remove structural numbering while preserving the full article heading."""
    value = _pictorial_subject(text)
    value = re.sub(r"^\s*(?:§\s*)?\d+(?:[.、]\d+)*[.、:：\-—\s]*", "", value)
    return value.strip()


def _short_label(text: str) -> str:
    """Return an exact, compact source phrase suitable for visible artwork text."""
    value = _section_heading(text)
    value = re.split(r"[：:，,。！？!?；;—]", value, maxsplit=1)[0].strip()
    return value if len(value) <= 12 else ""


def _text_constraint(*sources: str) -> str:
    labels = (_short_label(source) for source in sources)
    label = next((label for label in labels if label), "核心概念")
    return (
        f"可见文字：仅可使用原文短标签“{label}”，文字必须逐字准确；"
        "若无法准确呈现则省略。不得添加其他文字、数字、Logo 或水印。"
    )


def _key_points(topic: Dict[str, Any]) -> List[str]:
    return [p for p in (topic.get("key_points") or []) if p]


def _inline_point(topic: Dict[str, Any], index: int) -> str:
    """Return the key_point used for the ``index``-th inline prompt."""
    kps = [_pictorial_subject(p) for p in _key_points(topic)]
    if kps:
        return kps[index] if index < len(kps) else kps[-1]
    title = _pictorial_subject(topic.get("title") or "")
    return title or "抽象场景"


def _domain_constraint(topic: Dict[str, Any]) -> str:
    """Keep visual props relevant instead of adding generic science decor."""
    category = _pictorial_subject(topic.get("category") or "")
    if any(token in category for token in ("心理", "认知", "行为", "社会学")):
        return (
            "这是行为与社会科学主题，用人物选择、空间路径或群体差异表达；"
            "不得使用烧瓶、试管、分子结构、化学公式、显微镜或装饰性柱状图。"
        )
    return "画面中的器材和符号必须直接属于主题领域，不添加通用科研装饰。"


def _cover_prompt(topic: Dict[str, Any], brief: Optional[str] = None) -> str:
    """Cover-image prompt — sets the article's visual identity."""
    category = _pictorial_subject(topic.get("category") or "")
    source = _pictorial_subject(brief or _inline_point(topic, 0))
    return (
        f"{_KNOWLEDGE_STYLE}\n"
        f"画面类型：单幅概念封面。主题领域：{category}。\n"
        f"核心判断与文章依据：{source}\n"
        "画面任务：选择一个正文中的具体瞬间，用人物正在进行的动作、真实环境和可见反差"
        "呈现核心判断；不要把多个观点拼成信息图。"
        f"{_CONTENT_GROUNDING}\n"
        f"{_text_constraint(topic.get('title') or '', source)}\n"
        f"{_domain_constraint(topic)}{_COVER_COMPOSITION_CONSTRAINT}"
    )


def _inline_prompts(
    topic: Dict[str, Any], briefs: Optional[List[Any]] = None
) -> List[str]:
    """Build four prompts from the article's actual section headings and prose."""
    sections: List[Tuple[str, str]] = []
    for index in range(4):
        entry = briefs[index] if briefs and index < len(briefs) else None
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            heading = _pictorial_subject(str(entry[0]))
            source = _pictorial_subject(str(entry[1]))
        elif entry:
            heading = ""
            source = _pictorial_subject(str(entry))
        else:
            heading = ""
            source = _inline_point(topic, index)
        sections.append((heading, source))

    prompts = []
    for heading, source in sections:
        chapter = f"章节：{heading}。\n" if heading else ""
        prompts.append(
            f"{_KNOWLEDGE_STYLE}\n"
            f"{chapter}核心判断与文章依据：{source}\n"
            "画面任务：先识别这段正文唯一最重要的判断，再选择能直接证明它的一个具体瞬间；"
            "明确画出人物或主体正在进行的动作、真实地点，以及支持判断的可见反差。"
            f"{_CONTENT_GROUNDING}\n"
            f"{_text_constraint(heading, source, topic.get('title') or '')}\n"
            f"{_domain_constraint(topic)}{_COMPOSITION_CONSTRAINT}"
        )
    return prompts


def _visual_brief(markdown_fragment: str, limit: int = 420) -> str:
    """Turn a Markdown section into a compact, image-model grounding brief."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", markdown_fragment)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"^>.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"[`*_#]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    boundary = max(clipped.rfind(mark) for mark in "。！？；")
    return clipped[: boundary + 1] if boundary >= limit // 2 else clipped.rstrip()


def _article_visual_briefs(markdown: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Extract the abstract and first four H2 headings with their visual context."""
    headings = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, re.MULTILINE))
    summary = ""
    sections: List[Tuple[str, str]] = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        brief = _visual_brief(markdown[match.end():end])
        if not brief:
            continue
        if "摘要" in match.group(1):
            summary = brief
        elif len(sections) < 4:
            sections.append((_section_heading(match.group(1)), brief))
    return summary, sections


def _image_prompts_for_workdir(workdir: Path, topic: Dict[str, Any]) -> Dict[str, str]:
    """Build and persist the exact prompts used by cover and inline images."""
    try:
        markdown = (workdir / "article.md").read_text(encoding="utf-8")
    except OSError:
        markdown = ""
    summary, sections = _article_visual_briefs(markdown)
    roles = ["cover", *[f"inline-{i}" for i in range(1, 5)]]
    values = [
        _cover_prompt(topic, summary or None),
        *_inline_prompts(topic, sections or None),
    ]
    prompts = dict(zip(roles, values))
    (workdir / "image-prompts.json").write_text(
        json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return prompts


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
    writing_settings: Optional[Dict[str, str]] = None,
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

    md_text = write_article(topic, client=client, settings=writing_settings)

    cover_rel = "images/cover.jpg"
    inline_rels = [f"images/inline-{i}.jpg" for i in range(1, 5)]
    md_with_images = _insert_images(md_text, cover_rel, inline_rels)

    md_file = workdir / "article.md"
    md_file.write_text(md_with_images, encoding="utf-8")

    return workdir, [cover_rel, *inline_rels]


# ── 步骤 2：生成图片（显式单 Provider）─────────────────────────────────
def generate_images_in_workdir(
    workdir: Path,
    topic: Dict[str, Any],
    image_rels: List[str],
    image_settings: Dict[str, str],
) -> Literal["real"]:
    """Generate one cover and four inline images.

    Image generation is intentionally strict. The complete success status is
    written only after all five images were generated successfully.
    """
    img_dir = workdir / "images"
    img_dir.mkdir(exist_ok=True)
    state_path = workdir / "image-status.json"
    state_path.unlink(missing_ok=True)

    roles = ["cover", *[f"inline-{i}" for i in range(1, 5)]]
    prompts = _image_prompts_for_workdir(workdir, topic)

    for rel, role in zip(image_rels, roles):
        prompt = prompts[role]
        target = img_dir / Path(rel).name
        generate_image_with_provider(
            prompt,
            str(target),
            image_settings,
            size="cover" if role == "cover" else "article",
        )

    state_path.write_text(
        json.dumps({role: "real" for role in roles}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return "real"


def generate_single_image_in_workdir(
    workdir: Path,
    topic: Dict[str, Any],
    role: str,
    image_settings: Dict[str, str],
) -> Literal["real"]:
    """Regenerate one reviewed image, replacing it only after success."""
    roles = ["cover", *[f"inline-{i}" for i in range(1, 5)]]
    if role not in roles:
        raise ValueError(f"不支持的图片位置：{role}")
    prompts = _image_prompts_for_workdir(workdir, topic)
    target = workdir / "images" / f"{role}.jpg"
    state_path = workdir / "image-status.json"
    try:
        states = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        states = {}
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        generate_image_with_provider(
            prompts[role],
            str(temporary),
            image_settings,
            size="cover" if role == "cover" else "article",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    states[role] = "real"
    state_path.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")
    return "real"


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
