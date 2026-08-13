#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview history persistence.

Stores the last N previews so the user can browse / re-publish older
articles without re-running the LLM. Persists to a JSON file under
``webapp/_data/history.json`` so a container restart does not lose
history (within the bind-mounted webapp/ tree).

HistoryEntry = {
    id: int,                 # monotonic, oldest-first
    created_at: str,         # ISO timestamp
    topic_id, title, category, theme
    html: str,               # rendered themed HTML (with data: image URIs)
    workdir: str             # absolute path to /tmp/ws-render-XXX — used for publish
    image_mode: str          # "real" | "mixed" | "placeholder"
}
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

# webapp/history.py → webapp/_data/history.json
_DATA_DIR = Path(__file__).resolve().parent / "_data"
_HISTORY_FILE = _DATA_DIR / "history.json"
_MAX_ENTRIES = int(os.environ.get("WS_HISTORY_MAX", "10"))

_lock = threading.RLock()
_entries: List[Dict[str, Any]] = []
_next_id: int = 1


@contextmanager
def _locked():
    """Serialize history mutations across threads and Gunicorn processes."""
    with _lock:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        lock_path = _DATA_DIR / ".history.lock"
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            try:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except ImportError:
                fcntl = None
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load() -> None:
    global _entries, _next_id
    if _HISTORY_FILE.exists():
        try:
            raw = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _entries = []
            _next_id = 1
            return
        _entries = list(raw.get("entries", []))
        _next_id = int(raw.get("next_id", len(_entries) + 1))
    else:
        _entries = []
        _next_id = 1


def _save() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"next_id": _next_id, "entries": _entries}
    # atomic write: tmp file + rename, so a crash mid-write doesn't truncate
    fd, tmp = tempfile.mkstemp(prefix=".history-", dir=str(_DATA_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _HISTORY_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(entry: Dict[str, Any]) -> int:
    """Add a new history entry. Trims to _MAX_ENTRIES oldest-first.

    The ``html`` field is stripped here — it lived as a 1.7 MB blob in
    history.json and forced every /api/history/<id> response to ferry
    a base64-embedded iframe through JSON. The iframe now loads from
    /api/history/<id>/html instead.
    """
    global _next_id
    with _locked():
        _load()
        clean = {k: v for k, v in entry.items() if k != "html"}
        new_entry = {"id": _next_id, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     **clean}
        _next_id += 1
        _entries.append(new_entry)
        # Trim from the front if over capacity
        while len(_entries) > _MAX_ENTRIES:
            _entries.pop(0)
        _save()
        return new_entry["id"]


def delete(entry_id: int) -> bool:
    """Remove an entry by id. Returns True if it existed, False otherwise."""
    global _next_id
    with _locked():
        _load()
        before = len(_entries)
        _entries[:] = [e for e in _entries if e["id"] != entry_id]
        if len(_entries) == before:
            return False
        _save()
        return True


def list_entries() -> List[Dict[str, Any]]:
    """Return entries newest-first (most recent at index 0)."""
    with _locked():
        _load()
        return list(reversed(_entries))


def get(entry_id: int) -> Optional[Dict[str, Any]]:
    with _locked():
        _load()
        for e in _entries:
            if e["id"] == entry_id:
                return e
        return None


def update(entry_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an existing entry and persist it. Immutable identity fields stay intact."""
    with _locked():
        _load()
        for entry in _entries:
            if entry["id"] == entry_id:
                safe = {k: v for k, v in changes.items() if k not in {"id", "created_at", "workdir"}}
                entry.update(safe)
                _save()
                return dict(entry)
        return None


def clear() -> None:
    global _entries, _next_id
    with _locked():
        _entries = []
        _next_id = 1
        if _HISTORY_FILE.exists():
            _HISTORY_FILE.unlink()
