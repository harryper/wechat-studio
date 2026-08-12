#!/usr/bin/env python3
"""Add new topics to the knowledge corpus."""

import argparse
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS_PATH = SKILL_DIR / "references" / "knowledge-corpus.yaml"
VALID_CATEGORIES = {
    "cognitive_bias",
    "decision_theory",
    "philosophy",
    "psychology",
    "economics",
    "paradox",
}
REQUIRED_FIELDS = {"id", "title", "category", "key_points", "origin"}


def next_id(existing: list[dict]) -> str:
    """Return next free ID in kb-NNN format."""
    if not existing:
        return "kb-001"
    max_n = max(int(t["id"].split("-")[1]) for t in existing)
    if max_n >= 9999:
        raise RuntimeError("No free IDs up to kb-9999")
    return f"kb-{max_n + 1:03d}"


def validate_topic(topic: dict) -> None:
    """Raise ValueError if topic is malformed."""
    missing = REQUIRED_FIELDS - set(topic.keys())
    if missing:
        raise ValueError(f"missing required field: {missing}")
    if topic["category"] not in VALID_CATEGORIES:
        raise ValueError(f"invalid category: {topic['category']}")
    if not 3 <= len(topic["key_points"]) <= 5:
        raise ValueError(
            f"key_points must have 3-5 bullets, got {len(topic['key_points'])}"
        )
    if not topic["origin"].strip():
        raise ValueError("origin cannot be empty")


def append_topic(corpus_path: Path, topic: dict) -> None:
    """Append a validated topic to corpus YAML."""
    validate_topic(topic)
    with open(corpus_path, "r", encoding="utf-8") as f:
        corpus = yaml.safe_load(f)
    if any(t["id"] == topic["id"] for t in corpus):
        raise ValueError(f"duplicate ID: {topic['id']}")
    corpus.append(topic)
    with open(corpus_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(corpus, f, allow_unicode=True, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(description="Add topic to knowledge corpus")
    parser.add_argument("--title", required=True, help="Topic title")
    parser.add_argument("--category", required=True, choices=sorted(VALID_CATEGORIES))
    parser.add_argument("--key-points", nargs="+", required=True, help="3-5 bullet points")
    parser.add_argument("--origin", required=True, help="Origin/background")
    parser.add_argument("--caution", default="no", help="Caution flag")
    args = parser.parse_args()

    corpus = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
    topic = {
        "id": next_id(corpus),
        "title": args.title,
        "category": args.category,
        "key_points": args.key_points,
        "origin": args.origin,
        "caution": args.caution,
    }
    append_topic(CORPUS_PATH, topic)
    print(f"✅ Added {topic['id']} — {topic['title']}")


if __name__ == "__main__":
    main()