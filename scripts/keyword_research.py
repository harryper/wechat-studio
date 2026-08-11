#!/usr/bin/env python3
"""Lookup estimated search volume for academic concept titles."""

import sys
from typing import Optional


def _fetch(title: str) -> dict:
    """Fetch from external API. Default implementation: stub."""
    # No-op default; production wires to 百度指数 / 微信指数 API
    return {"volume": 0, "related": []}


def research(title: str) -> dict:
    """Return {estimated_volume, related_keywords} for a concept title.

    Failure-tolerant: returns empty result on exception.
    """
    try:
        data = _fetch(title)
        return {
            "estimated_volume": int(data.get("volume", 0)),
            "related_keywords": list(data.get("related", [])),
        }
    except Exception as e:
        print(f"[warn] keyword_research failed: {e}", file=sys.stderr)
        return {"estimated_volume": 0, "related_keywords": []}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Look up academic concept search volume")
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    print(research(args.title))