"""File-backed state for asynchronous Web generation jobs.

Job JSON files live in the bind-mounted ``webapp/_data/jobs`` directory so
any Gunicorn worker can answer polling requests. The thread that accepted a
job performs the work; state remains inspectable across worker recycling.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


_JOBS_DIR = Path(__file__).resolve().parent / "_data" / "jobs"
_MAX_JOBS = int(os.environ.get("WS_JOB_MAX", "100"))
_lock = threading.RLock()


def _path(job_id: str) -> Path:
    return _JOBS_DIR / f"{job_id}.json"


def _write(job: Dict[str, Any]) -> None:
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".job-", dir=str(_JOBS_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _path(job["id"]))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    job = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "status": "queued",
        "phase": "queued",
        "progress": 0,
        "created_at": now,
        "updated_at": now,
        "payload": payload,
        "result": None,
        "error": None,
    }
    with _lock:
        _write(job)
        paths = sorted(_JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in paths[_MAX_JOBS:]:
            old.unlink(missing_ok=True)
    return job


def get(job_id: str) -> Optional[Dict[str, Any]]:
    if not job_id or any(c not in "0123456789abcdef" for c in job_id):
        return None
    path = _path(job_id)
    with _lock:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


def update(job_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    with _lock:
        job = get(job_id)
        if job is None:
            return None
        job.update(changes)
        job["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write(job)
        return job


def mark_interrupted_jobs() -> int:
    """Mark jobs abandoned by a previous process as failed."""
    count = 0
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        for path in _JOBS_DIR.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if job.get("status") in {"queued", "running"}:
                job.update({
                    "status": "failed",
                    "phase": "interrupted",
                    "error": "服务进程重启，任务已中断，请重新提交。",
                })
                job["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _write(job)
                count += 1
    return count
