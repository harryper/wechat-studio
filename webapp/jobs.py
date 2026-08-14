"""D1-backed asynchronous generation job state."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .d1_client import client


def create(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    result = client.post(
        "/jobs",
        {
            "kind": kind,
            "payload": payload,
            "history_id": payload.get("history_id"),
        },
    )
    return result["job"]


def get(job_id: str) -> Optional[Dict[str, Any]]:
    if not job_id or any(c not in "0123456789abcdef" for c in job_id) or len(job_id) != 32:
        return None
    result = client.get(f"/jobs/{job_id}", allow_404=True)
    return result.get("job") if result else None


def update(job_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    result = client.patch(f"/jobs/{job_id}", changes)
    return result.get("job")


def mark_interrupted_jobs() -> int:
    """Kept for API compatibility; interruption recovery is handled explicitly."""
    return 0
