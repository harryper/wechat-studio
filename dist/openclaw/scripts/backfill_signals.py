#!/usr/bin/env python3
"""
Backfill quality_signals field from old notes field in client history.yaml.

Extracts subagent review scores from notes string and writes them as
structured fields, enabling future stats-driven selection.

Reads each article independently (split on `^- date:` markers) so a
single malformed article does not cause the whole file to be dropped.

Usage:
    python3 backfill_signals.py --client zhulv
    python3 backfill_signals.py --client zhulv --dry-run
"""
import argparse
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

SKILL_DIR = Path(__file__).parent.parent

# Regex patterns to extract review dimensions from notes
DIMENSION_PATTERNS = {
    "title_score": r"标题\s*(\d+(?:\.\d+)?)\s*[/／]",
    "hook_score": r"开头\s*(\d+(?:\.\d+)?)\s*[/／]",
    "golden_score": r"金句\s*(\d+(?:\.\d+)?)\s*[/／]",
    "ending_score": r"结尾\s*(\d+(?:\.\d+)?)\s*[/／]",
    "framework_fit": r"客户契合\s*(\d+(?:\.\d+)?)\s*[/／]",
}


def extract_signals(notes: str) -> Optional[dict]:
    """Extract quality signals from notes string. Returns None if nothing extractable."""
    if not notes:
        return None
    signals = {}
    for field, pattern in DIMENSION_PATTERNS.items():
        match = re.search(pattern, notes)
        if match:
            try:
                signals[field] = float(match.group(1))
            except ValueError:
                pass
    return signals if signals else None


def parse_articles(history_path: Path):
    """Parse history.yaml article-by-article so one bad block doesn't drop the file.

    Returns (articles, raw_blocks) where:
      - articles is a list of parsed dicts (one per well-formed block)
      - raw_blocks is the corresponding list of raw text blocks in order;
        blocks that failed to parse are kept as their raw text so we can
        round-trip the file without data loss.
    """
    text = history_path.read_text(encoding="utf-8")
    chunks = text.split("\n- date:")
    # First chunk already starts with `- date:`; the rest got split off.
    raw_blocks = []
    if chunks:
        raw_blocks.append(chunks[0])
        for c in chunks[1:]:
            raw_blocks.append("- date:" + c)

    articles = []
    parsed_flags = []
    fallback_used = 0
    for raw in raw_blocks:
        if not raw.strip():
            parsed_flags.append(True)  # empty block, nothing to keep
            continue
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            fallback_used += 1
            print(f"[warn] could not parse one article block; keeping as raw text: {e}", file=sys.stderr)
            articles.append(None)
            parsed_flags.append(False)
            continue
        if isinstance(parsed, list):
            # A chunk may contain multiple articles if a separator slipped by
            for item in parsed:
                if isinstance(item, dict):
                    articles.append(item)
            parsed_flags.append(True)
        elif isinstance(parsed, dict):
            articles.append(parsed)
            parsed_flags.append(True)
        else:
            parsed_flags.append(True)
    if fallback_used:
        print(f"[warn] {fallback_used} article(s) could not be parsed; kept as-is", file=sys.stderr)
    return articles, raw_blocks, parsed_flags


def main():
    parser = argparse.ArgumentParser(description="Backfill quality_signals from notes")
    parser.add_argument("--client", default="zhulv", help="Client name")
    parser.add_argument("--dry-run", action="store_true", help="Don't write, just print stats")
    args = parser.parse_args()

    history_path = SKILL_DIR / "clients" / args.client / "history.yaml"
    if not history_path.exists():
        print(f"[error] history.yaml not found for client '{args.client}'", file=sys.stderr)
        sys.exit(1)

    articles, raw_blocks, parsed_flags = parse_articles(history_path)

    updated = 0
    skipped = 0
    art_iter = iter(articles)
    out_blocks = []
    for raw, ok in zip(raw_blocks, parsed_flags):
        if not ok:
            # Keep malformed block verbatim (preserves the corrupted article)
            out_blocks.append(raw)
            continue
        if not raw.strip():
            continue
        article = next(art_iter, None)
        if article is None:
            out_blocks.append(raw)
            continue
        notes = article.get("notes", "") or ""
        signals = extract_signals(notes)
        if signals:
            article["quality_signals"] = signals
            updated += 1
        else:
            skipped += 1
        # Dump as a single-item list so we get the `- ` list-item marker back,
        # matching the original file's structure.
        dumped = yaml.dump(
            [article],
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        )
        # `dumped` ends with a trailing newline; strip it so joining with the
        # next block doesn't introduce a blank line gap.
        out_blocks.append(dumped.rstrip("\n"))

    if args.dry_run:
        print(f"[dry-run] Would update {updated} articles, skip {skipped}")
        return

    output = "\n".join(out_blocks)
    if not output.endswith("\n"):
        output += "\n"
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Updated {updated} articles with quality_signals")
    print(f"Skipped {skipped} (no extractable scores)")


if __name__ == "__main__":
    main()