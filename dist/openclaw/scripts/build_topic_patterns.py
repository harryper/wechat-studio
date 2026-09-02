#!/usr/bin/env python3
"""
Extract topic patterns from client history.yaml notes.

Builds a markdown reference of high-frequency framework × title-mode combinations
that can guide Step 3 topic selection and Step 5 title generation.

Usage:
    python3 build_topic_patterns.py --client zhulv --min-frequency 3
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).parent.parent

# Title mode detection patterns
TITLE_MODES = [
    ("数字开头", re.compile(r"^\s*\d")),
    ("反问/问句", re.compile(r"[？?]$")),
    ("价格戳心", re.compile(r"\d\s*[元块毛]|\d+\s*块钱?")),
    ("人物数字", re.compile(r"他\s*\d+|她\s*\d+|我\s*\d+\s*岁|\d+\s*岁")),
    ("反差陈述", re.compile(r"但是|然而|却|其实")),
    ("反常识陈述", re.compile(r"不是|没|别|别再|凭什么|居然")),
    ("场景钩人", re.compile(r"凌晨|深夜|那天|那天晚上|上[一二三四五六七八九十]周")),
]


def _detect_title_mode(title: str) -> str:
    """Return the most prominent title mode, or '其它'."""
    if not title:
        return "其它"
    for mode, pattern in TITLE_MODES:
        if pattern.search(title):
            return mode
    return "其它"


def _extract_framework(notes: str, framework: str = "") -> str:
    """Extract a single framework tag, normalizing the structured `framework` field
    (which uses `/` and `+` as tag delimiters) to its first segment.
    Falls back to scraping `framework:`/`框架:` from notes if the top-level field is empty."""
    if framework:
        raw = str(framework).strip()
        # Take the first tag (split on / or +), since `framework` is a composite field
        first = re.split(r"[+/]", raw, maxsplit=1)[0].strip()
        return first or raw
    if not notes:
        return "未知"
    # Match "framework: 反常识/带立场" or "framework: 痛点故事型"
    match = re.search(r"framework:\s*([^\s,，）)]+)", notes)
    if match:
        return match.group(1)
    # Match "框架: 反常识" patterns
    match = re.search(r"框架[为是]?\s*[：:]?\s*([^\s,，）)]+)", notes)
    if match:
        return match.group(1)
    return "未知"


def _load_history(client: str) -> list[dict]:
    history_path = SKILL_DIR / "clients" / client / "history.yaml"
    if not history_path.exists():
        print(f"[error] history.yaml not found for client '{client}'", file=sys.stderr)
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        # Whole-file parse failed — fall back to per-article split so a single bad
        # record doesn't zero out the whole history.
        print(f"[warn] {history_path.name} failed full parse, falling back to per-article: {exc}",
              file=sys.stderr)
        return _load_history_split(history_path)
    if not data:
        return []
    if isinstance(data, dict):
        return data.get("articles", [])
    return data if isinstance(data, list) else []


def _load_history_split(history_path: Path) -> list[dict]:
    """Parse a top-level YAML list by splitting on `- date:` markers and parsing each chunk.
    Used as a fallback when the whole file fails to parse due to a single corrupted entry."""
    text = history_path.read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^(?=- date:)", text)
    articles: list[dict] = []
    skipped = 0
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Re-add the list-dash prefix that split stripped off
        candidate = "- " + chunk if not chunk.startswith("- ") else chunk
        try:
            parsed = yaml.safe_load(candidate)
        except yaml.YAMLError:
            skipped += 1
            continue
        if isinstance(parsed, list) and parsed:
            entry = parsed[0]
            if isinstance(entry, dict):
                articles.append(entry)
    if skipped:
        print(f"[warn] skipped {skipped} unparseable article(s) in {history_path.name}",
              file=sys.stderr)
    return articles


def build_patterns(history: list[dict], min_frequency: int = 3) -> list[dict]:
    """
    Extract patterns from history. Returns list of pattern dicts:
        {
            "framework": str,
            "title_mode": str,
            "count": int,
            "examples": [{"date": str, "title": str}, ...],
            "word_count_avg": int,
        }
    """
    bucket = defaultdict(list)
    for article in history:
        title = article.get("title", "")
        notes = article.get("notes", "") or ""
        framework = _extract_framework(notes, article.get("framework", ""))
        title_mode = _detect_title_mode(title)
        # Skip very short early articles (mostly noise)
        wc = article.get("word_count", 0) or 0
        if wc and wc < 1200:
            continue
        key = (framework, title_mode)
        bucket[key].append({
            "date": article.get("date", ""),
            "title": title,
            "word_count": wc,
        })

    patterns = []
    for (framework, title_mode), articles in bucket.items():
        if len(articles) >= min_frequency:
            word_counts = [a["word_count"] for a in articles if a["word_count"]]
            patterns.append({
                "framework": framework,
                "title_mode": title_mode,
                "count": len(articles),
                "examples": articles[:3],  # top 3 most recent
                "word_count_avg": sum(word_counts) // max(len(word_counts), 1) if word_counts else 0,
            })

    # Sort by count desc
    patterns.sort(key=lambda p: p["count"], reverse=True)
    return patterns


def render_markdown(client: str, patterns: list[dict], total_articles: int) -> str:
    """Render patterns as a markdown reference file."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# 高表现 pattern 种子库 ({client})",
        "",
        f"> 自动从 {total_articles} 篇历史 notes 提取。生成时间: {today}。",
        "",
        "## 使用方式",
        "",
        "- Step 3 选题时, Agent 加载本文件到上下文, 匹配候选题的 `pattern_tag`",
        "- Step 5 标题生成时, 根据 `pattern_tag` 决定 3 个候选标题的模式分配",
        "- `pattern_tag` = `framework` × `title_mode` 的组合",
        "",
        "## Patterns",
        "",
    ]

    if not patterns:
        lines.append("(无足够样本, min-frequency 阈值可能过高)")
        return "\n".join(lines) + "\n"

    for i, p in enumerate(patterns, 1):
        letter = chr(ord("A") + i - 1)
        lines.append(f"### Pattern {letter}: {p['framework']} × {p['title_mode']}")
        lines.append("")
        lines.append(f"- 频次: {p['count']}")
        lines.append(f"- framework: {p['framework']}")
        lines.append(f"- title_mode: {p['title_mode']}")
        if p["word_count_avg"]:
            lines.append(f"- 平均字数: {p['word_count_avg']}")
        lines.append("- 代表作:")
        for ex in p["examples"]:
            lines.append(f"  - \"{ex['title']}\" ({ex['date']})")
        lines.append("")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Build topic patterns from history")
    parser.add_argument("--client", default="zhulv", help="Client name")
    parser.add_argument("--min-frequency", type=int, default=3, help="Minimum pattern frequency")
    parser.add_argument("--output", help="Output path (default: references/topic-patterns.md)")
    args = parser.parse_args()

    history = _load_history(args.client)
    if not history:
        print("No history found, aborting.", file=sys.stderr)
        sys.exit(1)

    patterns = build_patterns(history, args.min_frequency)
    md = render_markdown(args.client, patterns, len(history))

    output_path = Path(args.output) if args.output else SKILL_DIR / "references" / "topic-patterns.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    print(f"Wrote {len(patterns)} patterns to {output_path}")
    print(f"Source: {len(history)} articles, min-frequency={args.min_frequency}")


if __name__ == "__main__":
    main()
