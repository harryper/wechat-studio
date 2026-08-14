"""D1-backed WeChat publication records."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .d1_client import client


def record(
    history_id: int,
    *,
    status: str,
    remote_id: Optional[str] = None,
    response: Optional[Dict[str, Any]] = None,
    target: str = "draft",
) -> Dict[str, Any]:
    payload = client.post(
        "/publications",
        {
            "history_id": history_id,
            "status": status,
            "remote_id": remote_id,
            "response": response or {},
            "target": target,
        },
    )
    return payload["publication"]
