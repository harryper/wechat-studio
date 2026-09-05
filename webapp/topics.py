"""D1-backed topic center operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .d1_client import client


def _normalize(topic: Dict[str, Any]) -> Dict[str, Any]:
    context = topic.get("context") if isinstance(topic.get("context"), dict) else {}
    return {
        **topic,
        "key_points": context.get("key_points", []),
        "origin": context.get("origin", ""),
        "caution": context.get("caution", "no"),
        "prompt": context.get("prompt", ""),
    }


def list_topics(
    *,
    query: str = "",
    status: str = "available",
    category: str = "",
    source: str = "",
    client_name: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    payload = client.get(
        "/topics",
        params={
            "q": query,
            "status": status,
            "category": category,
            "source": source,
            "client": client_name,
            "limit": limit,
        },
    ) or {}
    return {
        "topics": [_normalize(item) for item in payload.get("topics", [])],
        "total": int(payload.get("total", 0)),
    }


def get_topic(topic_id: str) -> Optional[Dict[str, Any]]:
    payload = client.get(f"/topics/{quote(topic_id, safe='')}", allow_404=True)
    return _normalize(payload["topic"]) if payload else None


def create_topic(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = client.post("/topics", data)
    return _normalize(payload["topic"])


def upsert_corpus(items: List[Dict[str, Any]]) -> int:
    payload = client.post("/topics/bulk", {"topics": items})
    return int(payload.get("upserted", 0))


def set_status(topic_id: str, status: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = client.patch(
        f"/topics/{quote(topic_id, safe='')}",
        {"status": status, "details": details or {}},
    )
    return _normalize(payload["topic"])
