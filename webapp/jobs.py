"""Local file-backed asynchronous generation job state.

Each job is stored as an individual JSON file under ``_DATA_DIR / "jobs/"``.
Job IDs are 32-character lowercase hex strings.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .local_store import AtomicStore

log = logging.getLogger("wechat-studio")

_DATA_DIR = Path(os.environ.get("WS_DATA_DIR", Path(__file__).resolve().parent / "_data"))
_JOBS_DIR = _DATA_DIR / "jobs"

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _init_store(jobs_dir: Optional[Path] = None) -> None:
    """Re-point the jobs directory (used by tests to isolate data)."""
    global _JOBS_DIR
    if jobs_dir is not None:
        _JOBS_DIR = jobs_dir


def _job_path(job_id: str) -> Path:
    return _JOBS_DIR / f"{job_id}.json"


def _store_for(job_id: str) -> AtomicStore:
    return AtomicStore(_job_path(job_id))


def _valid_id(job_id: str) -> bool:
    return bool(job_id and _JOB_ID_RE.match(job_id))


def create(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
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
    store = _store_for(job_id)
    store.write(job)
    return copy.deepcopy(job)


def get(job_id: str) -> Optional[Dict[str, Any]]:
    if not _valid_id(job_id):
        return None
    path = _job_path(job_id)
    if not path.exists():
        return None
    store = _store_for(job_id)
    return copy.deepcopy(store.read())


def update(job_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    if not _valid_id(job_id):
        return None
    path = _job_path(job_id)
    if not path.exists():
        return None
    store = _store_for(job_id)
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _do_update(data):
        data.update(changes)
        return data

    store.update(_do_update)
    return copy.deepcopy(store.read())


def delete_job(job_id: str) -> bool:
    if not _valid_id(job_id):
        return False
    path = _job_path(job_id)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def delete_by_history_id(history_id: int) -> int:
    """Delete all job files whose payload.history_id matches."""
    count = 0
    if not _JOBS_DIR.exists():
        return 0
    for job_file in _JOBS_DIR.glob("*.json"):
        if job_file.name.endswith(".lock"):
            continue
        try:
            store = AtomicStore(job_file)
            data = store.read()
            payload = data.get("payload") or {}
            if payload.get("history_id") == history_id or str(payload.get("history_id")) == str(history_id):
                job_file.unlink(missing_ok=True)
                job_file.with_suffix(job_file.suffix + ".lock").unlink(missing_ok=True)
                count += 1
        except Exception as exc:
            log.warning("failed to inspect job %s: %s", job_file.name, exc)
    return count


def mark_interrupted_jobs() -> int:
    """Mark stale running/queued jobs as failed on startup."""
    count = 0
    if not _JOBS_DIR.exists():
        return 0
    for job_file in _JOBS_DIR.glob("*.json"):
        if job_file.name.endswith(".lock"):
            continue
        try:
            store = AtomicStore(job_file)
            data = store.read()
            if data.get("status") in ("queued", "running"):
                data["status"] = "failed"
                data["phase"] = "interrupted"
                data["error"] = "服务进程重启，任务已中断，请重新提交"
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                store.write(data)
                count += 1
        except Exception as exc:
            log.warning("failed to mark interrupted job %s: %s", job_file.name, exc)
    return count


def count() -> int:
    if not _JOBS_DIR.exists():
        return 0
    return sum(1 for f in _JOBS_DIR.glob("*.json") if not f.name.endswith(".lock"))
