#!/usr/bin/env python3
"""Migrate clients/{client}/history.yaml to add track + topic_id fields."""

from pathlib import Path

import yaml

NEEDED_FIELDS = {"track": "knowledge", "topic_id": None}


def migrate(history_path: Path) -> None:
    """Add missing fields to each entry. Idempotent. Doesn't overwrite."""
    if not history_path.exists():
        return
    with open(history_path, "r", encoding="utf-8") as f:
        history = yaml.safe_load(f) or []
    changed = False
    for entry in history:
        for key, default in NEEDED_FIELDS.items():
            if key not in entry:
                entry[key] = default
                changed = True
    if changed:
        with open(history_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(history, f, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate history.yaml schema")
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    path = Path(__file__).resolve().parent.parent / "clients" / args.client / "history.yaml"
    migrate(path)
    print(f"✅ Migrated {path}")