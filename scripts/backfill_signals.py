#!/usr/bin/env python3
"""
Backfill quality_signals field from old notes field in client history.yaml.

Pure text-level surgery — does NOT yaml.parse or yaml.dump the article body,
because the file has a mix of intact YAML (col 2 fields) and Task-3 damaged
YAML (col 0 fields from a previous broken implementation). Parsing either
form is unreliable; preserving original text and appending `quality_signals:`
to the article's tail is the only safe operation.

Approach:
  1. Split text on `\n- date:` boundaries (gives article blocks).
  2. For each block, scan for extractable review scores in the `notes:`
     field via regex over the raw text (no YAML parsing).
  3. If scores found AND no `quality_signals:` already present, append a
     new `  quality_signals:` block to the END of the article's text.
  4. Reassemble with the original `\n- date:` joiner.

Usage:
    python3 backfill_signals.py --client zhulv
    python3 backfill_signals.py --client zhulv --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent

# Regex patterns to extract review dimensions from notes
DIMENSION_PATTERNS = {
    "title_score": r"标题\s*(\d+(?:\.\d+)?)\s*[/／]",
    "hook_score": r"开头\s*(\d+(?:\.\d+)?)\s*[/／]",
    "golden_score": r"金句\s*(\d+(?:\.\d+)?)\s*[/／]",
    "ending_score": r"结尾\s*(\d+(?:\.\d+)?)\s*[/／]",
    "framework_fit": r"客户契合\s*(\d+(?:\.\d+)?)\s*[/／]",
}

# Total review score: "一审 X/70"
TOTAL_SCORE_PATTERN = re.compile(r"(?:一审|二审|三审)?\s*(\d+(?:\.\d+)?)\s*[/／]\s*70")


def extract_signals_from_text(block: str) -> dict | None:
    """Find `notes:` value in block text and extract scores. No YAML parse."""
    # Notes can span multiple lines (continuation at col 2). Capture first line
    # + any continuation lines (starting with 2 spaces).
    notes_match = re.search(r"notes:\s*([^\n]+(?:\n  [^\n]+)*)", block)
    if not notes_match:
        return None
    notes_text = notes_match.group(1)
    signals = {}
    for field, pattern in DIMENSION_PATTERNS.items():
        match = re.search(pattern, notes_text)
        if match:
            try:
                signals[field] = float(match.group(1))
            except ValueError:
                pass
    # Total /70 score (matches any "N/70" not preceded by dimension name; if
    # both per-dim and total exist we keep per-dim, with total as review_score).
    total_match = TOTAL_SCORE_PATTERN.search(notes_text)
    if total_match:
        try:
            signals["review_score"] = float(total_match.group(1))
        except ValueError:
            pass
    return signals if signals else None


def format_signals_yaml(signals: dict) -> str:
    """Render signals as a YAML block at col 2 indent, matching the file's style.

    Output has NO leading or trailing newline — caller controls spacing by
    prepending a newline before the block.
    """
    lines = ["  quality_signals:"]
    for key, value in signals.items():
        if isinstance(value, float) and value.is_integer():
            value_str = f"{int(value)}.0"
        else:
            value_str = str(value)
        lines.append(f"    {key}: {value_str}")
    return "\n".join(lines)


def split_blocks(text: str) -> tuple[list[str], list[str]]:
    """Split history.yaml into per-article raw blocks.

    Each block ends at the next `\n- date:` boundary. The first block
    INCLUDES its leading `- date:` (file starts with one). Subsequent
    blocks have their `- date:` prefix stripped — caller rejoins with
    `\n- date:`.
    """
    parts = text.split("\n- date:")
    blocks = []
    separators = []
    if parts:
        blocks.append(parts[0])
        separators.append("")
    for part in parts[1:]:
        blocks.append(part)
        separators.append("\n- date:")
    return blocks, separators


def main():
    parser = argparse.ArgumentParser(description="Backfill quality_signals from notes")
    parser.add_argument("--client", default="zhulv", help="Client name")
    parser.add_argument("--dry-run", action="store_true", help="Don't write, just print stats")
    args = parser.parse_args()

    history_path = SKILL_DIR / "clients" / args.client / "history.yaml"
    if not history_path.exists():
        print(f"[error] history.yaml not found for client '{args.client}'", file=sys.stderr)
        sys.exit(1)

    original_text = history_path.read_text(encoding="utf-8")
    blocks, separators = split_blocks(original_text)

    new_blocks = []
    updated = 0
    skipped = 0
    no_notes = 0

    for block in blocks:
        if not block.strip():
            new_blocks.append(block)
            continue

        if "quality_signals:" in block:
            skipped += 1
            new_blocks.append(block)
            continue

        signals = extract_signals_from_text(block)
        if not signals:
            no_notes += 1
            new_blocks.append(block)
            continue

        # Append signals block to end of article's raw text.
        # Find the last non-empty line and append after it.
        stripped = block.rstrip("\n")
        new_block = stripped + "\n" + format_signals_yaml(signals) + "\n"
        new_blocks.append(new_block)
        updated += 1

    if args.dry_run:
        print(f"[dry-run] Would update {updated} articles, skip {skipped}, no-notes {no_notes}")
        return

    parts = []
    for sep, block in zip(separators, new_blocks):
        parts.append(sep + block)
    output = "".join(parts)
    if not output.endswith("\n"):
        output += "\n"

    history_path.write_text(output, encoding="utf-8")
    print(f"Updated {updated} articles with quality_signals")
    print(f"Skipped {skipped} (already had quality_signals)")
    print(f"No-notes {no_notes} (no extractable scores)")


if __name__ == "__main__":
    main()