#!/usr/bin/env python3
"""Load knowledge corpus and pick next topic for writing."""

from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS_PATH = SKILL_DIR / "references" / "knowledge-corpus.yaml"


def load_corpus() -> list[dict]:
    """Load all topics from knowledge corpus YAML."""
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def used_topic_ids(client: str) -> set[str]:
    """Read history.yaml for a client and extract used topic_ids."""
    history_path = SKILL_DIR / "clients" / client / "history.yaml"
    if not history_path.exists():
        return set()
    with open(history_path, "r", encoding="utf-8") as f:
        history = yaml.safe_load(f) or []
    return {entry.get("topic_id") for entry in history if entry.get("topic_id")}


def next_topic(client: str) -> dict:
    """Pick first unused topic from corpus. Round-robin when exhausted."""
    corpus = load_corpus()
    used = used_topic_ids(client)
    for topic in corpus:
        if topic["id"] not in used:
            return topic
    return corpus[0]


def exhaustion_pct(client: str) -> float:
    """Return fraction of corpus used by client (0.0–1.0)."""
    corpus = load_corpus()
    used = used_topic_ids(client)
    return len(used & {t["id"] for t in corpus}) / len(corpus)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pick next topic from knowledge corpus")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--dry-run", action="store_true", help="Just print, don't write")
    args = parser.parse_args()

    topic = next_topic(args.client)
    pct = exhaustion_pct(args.client)
    print(f"Next topic: {topic['id']} — {topic['title']}")
    print(f"Corpus exhaustion: {pct:.0%}")
    if pct >= 0.8:
        print("WARNING: corpus >=80% used. Run scripts/expand_corpus.py")
    if pct >= 1.0:
        print("100% used - round-robin restart")
