#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM-based article writer for the knowledge track.

Replaces the structural mock in webapp/synthesize.py with a real
article-generation pipeline that calls the project's configured LLM
(MiniMax via the Anthropic-compatible Messages API).

Reads:
    - references/frameworks-academic.md  (section structure guidance)
    - topic metadata from knowledge-corpus.yaml  (origin, key_points, ...)

Writes:
    - a markdown article string in the 2500-4000 字 range, structured
      per the chosen academic framework, with category line and a
      "本文为逻辑梳理" footer left to cli.py to inject (idempotently).

Strict mode: any API / parse failure raises — caller surfaces the error
to the user. No fallback to a mock article.
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import anthropic


# ── 路径常量 ─────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent
FRAMEWORKS_DOC = SKILL_DIR / "references" / "frameworks-academic.md"

sys.path.insert(0, str(SKILL_DIR))  # scripts/ 直接运行时仓库根不在 sys.path
from toolkit import env_config
from toolkit.llm_adapters import generate_text


# ── 框架选择 ─────────────────────────────────────────────────────────
_FRAMEWORK_KEYWORDS = [
    ("origin", ("起源", "演变", "提出", "诞生", "源流")),
    ("mechanism", ("原理", "机制", "定律", "法则", "规律")),
    ("experiment", ("实验", "研究", "测试", "试验", "调查")),
]

_FRAMEWORK_OUTLINES = {
    "origin": (
        "框架 1：起源-演变-影响",
        "结构（按顺序）：\n"
        "  # 标题\n"
        "  > **分类**：{category}　　**主题 ID**：`{topic_id}`\n"
        "  ## 摘要\n"
        "  ## § 1 起源\n"
        "  ## § 2 发展演变\n"
        "  ## § 3 影响与应用\n"
        "  ## § 4 反直觉点\n"
        "章节要求（只约束正文长度，不属于标题）：\n"
        "  - 摘要：约 100 字\n"
        "  - 起源：300-500 字\n"
        "  - 发展演变：300-500 字\n"
        "  - 影响与应用：400-600 字\n"
        "  - 反直觉点：200-300 字",
    ),
    "mechanism": (
        "框架 2：原理-证据-应用",
        "结构（按顺序）：\n"
        "  # 标题\n"
        "  > **分类**：{category}　　**主题 ID**：`{topic_id}`\n"
        "  ## 摘要\n"
        "  ## § 1 原理阐释\n"
        "  ## § 2 证据链\n"
        "  ## § 3 现代应用\n"
        "  ## § 4 局限与边界\n"
        "章节要求（只约束正文内容和长度，不属于标题）：\n"
        "  - 摘要：约 100 字\n"
        "  - 原理阐释：说明核心机制，约 600 字\n"
        "  - 证据链：3-4 个经典实验或案例，共约 800 字\n"
        "  - 现代应用：2-3 个落地场景，共约 600 字\n"
        "  - 局限与边界：约 400 字",
    ),
    "experiment": (
        "框架 3：经典实验-当代启示",
        "结构（按顺序）：\n"
        "  # 标题\n"
        "  > **分类**：{category}　　**主题 ID**：`{topic_id}`\n"
        "  ## 摘要\n"
        "  ## § 1 实验背景\n"
        "  ## § 2 实验设计\n"
        "  ## § 3 结果与争议\n"
        "  ## § 4 当代启示\n"
        "章节要求（只约束正文内容和长度，不属于标题）：\n"
        "  - 摘要：约 100 字\n"
        "  - 实验背景：包含时代背景、研究者和原始问题，约 500 字\n"
        "  - 实验设计：包含变量、样本和方法，约 600 字\n"
        "  - 结果与争议：包含数据和后续修订，约 700 字\n"
        "  - 当代启示：包含 2-3 个现代应用，约 600 字",
    ),
}


def select_framework(topic: Dict[str, Any]) -> str:
    """Pick a framework key based on the topic's title and category.

    Mirrors the selection logic documented in references/frameworks-academic.md.
    Falls back to ``origin`` (the default framework) when nothing matches.
    """
    haystack = (topic.get("title", "") + " " + topic.get("category", "")).lower()
    for key, keywords in _FRAMEWORK_KEYWORDS:
        for kw in keywords:
            if kw.lower() in haystack:
                return key
    return "origin"


def _build_outline(topic: Dict[str, Any]) -> str:
    key = select_framework(topic)
    label, template = _FRAMEWORK_OUTLINES[key]
    outline = template.format(
        category=topic.get("category", ""),
        topic_id=topic.get("id", ""),
    )
    return (
        label
        + "\n\n"
        + outline
        + "\n标题输出规则：标题中不得出现字数、数量或结构说明，也不得照抄章节要求中的括号内容。"
    )


# ── LLM 客户端 ───────────────────────────────────────────────────────
def _build_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        base_url=env_config.require("ANTHROPIC_BASE_URL", "写作使用的 Anthropic 兼容端点"),
        api_key=env_config.require("ANTHROPIC_API_KEY", "写作端点的 API Key"),
    )


def _load_client_context(client: Optional[str]) -> str:
    """Load optional style/playbook context for Web and CLI generation."""
    if not client:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", client):
        raise RuntimeError("客户名只能包含字母、数字、下划线和连字符。")
    client_dir = SKILL_DIR / "clients" / client
    chunks = []
    style_path = client_dir / "style.yaml"
    if style_path.exists():
        try:
            import yaml
            style = yaml.safe_load(style_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            raise RuntimeError(f"读取客户 style.yaml 失败：{e}") from e
        selected = {
            key: style.get(key)
            for key in ("tone", "voice", "content_style", "blacklist")
            if style.get(key)
        }
        if selected:
            chunks.append("客户风格：\n" + yaml.safe_dump(selected, allow_unicode=True, sort_keys=False))
    playbook_path = client_dir / "playbook.md"
    if playbook_path.exists():
        chunks.append("客户 Playbook（优先于通用风格）：\n" + playbook_path.read_text(encoding="utf-8"))
    return "\n\n".join(chunks)


def _build_prompt(topic: Dict[str, Any], client: Optional[str] = None) -> str:
    outline = _build_outline(topic)
    key_points = topic.get("key_points") or []
    kp_lines = "\n".join(f"- {p}" for p in key_points) or "-（暂无）"
    origin = (topic.get("origin") or "（暂无）").strip()
    caution = topic.get("caution") or "no"
    caution_note = (
        "该主题在公共传播中存在大量简化版本，请围绕原始文献/经典来源写作，避免给出未经验证的轶事。"
        if caution == "yes"
        else "无需特别警示，按主题本身的张力展开。"
    )
    client_context = _load_client_context(client)
    client_section = f"\n\n{client_context}" if client_context else ""
    return f"""你是「微信公众号·知识科普」专栏的撰稿人，正在为一篇深度科普长文打底。请按 Markdown 输出正文，禁止任何额外评论。

主题信息：
- 主题 ID：{topic.get("id", "")}
- 主题标题：{topic.get("title", "")}
- 分类：{topic.get("category", "")}
- 起源/背景：{origin}
- 关键要点：
{kp_lines}

使用的写作框架：
{outline}

写作要求：
- 全文 2500-4000 中文字（不含标点）
- 标题：学术定义式，30-50 字，可带副标题
- 摘要：约 100 字，点题即可
- 语气：academic but readable — 避免大段术语堆砌，避免空洞排比
- 引用经典文献/实验时给出人物、年份、方法名；不要编造具体数据
- 不需要加任何插图占位符，图片由后续流程单独插入
- 不需要写免责声明 — 由系统统一注入（"本文为逻辑梳理，非学术研究"）
- 注意：{caution_note}
{client_section}

直接输出 Markdown 正文，开头是 `# 标题`，中间用 ## 切分章节。不要任何开场白或收尾评论。"""


# ── 文章清洗 ─────────────────────────────────────────────────────────
_LEADING_FENCE_RE = re.compile(r"^\s*```(?:markdown|md)?\s*\n", re.IGNORECASE)
_TRAILING_FENCE_RE = re.compile(r"\n```\s*$", re.IGNORECASE)
_HEADING_PAREN_RE = re.compile(r"[（(]([^（）()]*)[）)]")
_HEADING_CONSTRAINT_RE = re.compile(
    r"\d.*(?:字|个\s*(?:实验|案例|场景|要点|章节|部分|应用))"
)


def _strip_code_fence(text: str) -> str:
    """Remove a single wrapping ```markdown ... ``` fence if the model added one."""
    cleaned = text.strip()
    m = _LEADING_FENCE_RE.match(cleaned)
    if m and _TRAILING_FENCE_RE.search(cleaned):
        cleaned = cleaned[m.end(): _TRAILING_FENCE_RE.search(cleaned).start()]
    return cleaned.strip()


def _strip_heading_constraints(text: str) -> str:
    """Remove copied length/count instructions from Markdown headings only."""
    cleaned_lines = []
    for line in text.splitlines():
        if re.match(r"^\s*#{1,6}\s+", line):
            line = _HEADING_PAREN_RE.sub(
                lambda match: ""
                if _HEADING_CONSTRAINT_RE.search(match.group(1))
                else match.group(0),
                line,
            ).rstrip()
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _enforce_title(text: str, fallback_title: str) -> str:
    """Make sure the first non-empty line is an H1. Prepend if missing."""
    first_heading = next(
        (line for line in text.splitlines() if line.strip()),
        "",
    )
    if first_heading.lstrip().startswith("# "):
        return text
    return f"# {fallback_title}\n\n" + text


# ── 公共入口 ─────────────────────────────────────────────────────────
def write_article(
    topic: Dict[str, Any],
    *,
    client: Optional[str] = None,
    prompt: Optional[str] = None,
    settings: Optional[Dict[str, str]] = None,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    timeout: int = 240,
) -> str:
    """Generate a real article for ``topic`` via the configured LLM.

    Returns a markdown string suitable to feed into cli.py preview / publish.
    Raises RuntimeError on any API / parse failure — caller surfaces the
    error to the user, no silent fallback.
    """
    if settings is None:
        effective_settings = {
            "provider_id": "legacy-anthropic",
            "adapter": "anthropic_messages",
            "base_url": env_config.require(
                "ANTHROPIC_BASE_URL", "写作使用的 Anthropic 兼容端点"
            ),
            "api_key": env_config.require("ANTHROPIC_API_KEY", "写作端点的 API Key"),
            "model": model or env_config.require("ANTHROPIC_MODEL", "写作模型名"),
        }
    else:
        effective_settings = dict(settings)
    if model is not None:
        effective_settings["model"] = model
    effective_prompt = (
        prompt
        if isinstance(prompt, str) and prompt.strip()
        else _build_prompt(topic, client=client)
    )
    raw = generate_text(
        effective_prompt,
        effective_settings,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    text = _strip_heading_constraints(_strip_code_fence(raw))
    text = _enforce_title(text, fallback_title=topic.get("title", "未命名主题"))
    return text


# ── CLI 入口 ─────────────────────────────────────────────────────────
def _main(argv: list) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Generate a knowledge-track article via LLM")
    ap.add_argument("--topic", required=True,
                    help="topic id (kb-NNN) — loaded from knowledge-corpus.yaml")
    ap.add_argument("--out", "-o", default="-",
                    help="output path, or '-' for stdout (default)")
    args = ap.parse_args(argv)

    import yaml
    corpus_path = SKILL_DIR / "references" / "knowledge-corpus.yaml"
    with open(corpus_path, encoding="utf-8") as f:
        corpus = yaml.safe_load(f) or []
    topic = next((t for t in corpus if t.get("id") == args.topic), None)
    if topic is None:
        print(f"未找到主题 {args.topic}", file=sys.stderr)
        return 2

    md = write_article(topic)
    if args.out == "-":
        sys.stdout.write(md)
    else:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"Wrote: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
