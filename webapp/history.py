"""D1-backed article history and content lifecycle persistence."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .d1_client import client


def add(entry: Dict[str, Any]) -> int:
    payload = client.post("/articles", entry)
    return int(payload["article"]["id"])


def delete(entry_id: int) -> bool:
    payload = client.get(f"/articles/history/{entry_id}", allow_404=True)
    if payload is None:
        return False
    client.delete(f"/articles/history/{entry_id}")
    return True


def list_entries(*, status: str = "", query: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    payload = client.get(
        "/articles",
        params={"status": status, "q": query, "limit": limit},
    ) or {}
    return list(payload.get("articles", []))


def get(entry_id: int) -> Optional[Dict[str, Any]]:
    payload = client.get(f"/articles/history/{entry_id}", allow_404=True)
    return payload.get("article") if payload else None


def update(entry_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    safe = {
        key: value
        for key, value in changes.items()
        if key not in {"id", "article_id", "created_at"}
    }
    payload = client.patch(f"/articles/history/{entry_id}", safe)
    return payload.get("article")


def clear() -> None:
    """Archive all active entries. Intended for maintenance and tests."""
    for entry in list_entries(limit=200):
        delete(int(entry["id"]))
