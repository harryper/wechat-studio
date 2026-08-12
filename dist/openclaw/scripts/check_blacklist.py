#!/usr/bin/env python3
"""
Check candidate titles/topics against client blacklist + global banned words.

Usage:
    python3 check_blacklist.py --text "..." --client zhulv
    python3 check_blacklist.py --text "..." --blacklist "最全" "最强"

Exit codes:
    0 = passed (no blacklist hits)
    1 = failed (one or more blacklist hits)
    2 = error (file load failed, but warn-and-pass behavior still emits output)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent

# Global banned words (titles bait / 标题党通用词)
GLOBAL_BANNED = [
    "震惊", "必看", "转疯了", "不转不是中国人",
    "99%的人不知道", "99% 的人不知道",
    "史上最", "错过等一年", "全网最", "全网最强",
]

# Suggestion templates per pattern
SUGGESTIONS = {
    "最全": "改为反常识/反问句, 避免'最全/最强'类绝对化标题",
    "最强": "改为反常识/反问句, 避免'最全/最强'类绝对化标题",
    "必看": "改为具体场景或数字, 避免命令式标题",
    "震惊": "去掉'震惊'类词, 用具体数字或场景替代",
}


def _compile_pattern(keyword: str) -> re.Pattern | None:
    """Compile a blacklist keyword into a literal substring regex."""
    try:
        # Escape special chars, allow space inside keywords
        escaped = re.escape(keyword.strip())
        return re.compile(escaped)
    except re.error:
        return None


def check(text: str, blacklist: list[str]) -> dict:
    """
    Check text against client blacklist + global banned words.

    Returns:
        {
            "passed": bool,
            "hits": [{"pattern": str, "position": int, "suggestion": str}, ...],
            "suggestion": str | None,
        }
    """
    if not text:
        return {"passed": True, "hits": [], "suggestion": None}

    combined = list(blacklist) + GLOBAL_BANNED
    hits = []
    suggestions = set()

    for keyword in combined:
        if not keyword or not keyword.strip():
            continue
        pattern = _compile_pattern(keyword)
        if pattern is None:
            continue
        match = pattern.search(text)
        if match:
            hits.append({
                "pattern": keyword,
                "position": match.start(),
                "suggestion": SUGGESTIONS.get(keyword, f"去掉 '{keyword}' 类词"),
            })
            suggestions.add(SUGGESTIONS.get(keyword, f"去掉 '{keyword}' 类词"))

    return {
        "passed": len(hits) == 0,
        "hits": hits,
        "suggestion": " | ".join(sorted(suggestions)) if suggestions else None,
    }


def _load_client_blacklist(client: str) -> list[str]:
    """Load blacklist from clients/{client}/style.yaml. Warn on failure."""
    style_path = SKILL_DIR / "clients" / client / "style.yaml"
    if not style_path.exists():
        print(f"[warn] style.yaml not found for client '{client}'", file=sys.stderr)
        return []
    try:
        import yaml
        with open(style_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("blacklist", []) or []
    except Exception as e:
        print(f"[warn] failed to load blacklist for '{client}': {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(description="Check text against blacklist")
    parser.add_argument("--text", required=True, help="Candidate title/topic text")
    parser.add_argument("--client", default="zhulv", help="Client name")
    parser.add_argument("--blacklist", nargs="*", default=[], help="Inline blacklist (overrides style.yaml)")
    args = parser.parse_args()

    blacklist = args.blacklist if args.blacklist else _load_client_blacklist(args.client)
    result = check(args.text, blacklist)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()