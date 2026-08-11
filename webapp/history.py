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
    image_mode: str          # "real" | "placeholder"
}
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# webapp/history.py → webapp/_data/history.json
_DATA_DIR = Path(__file__).resolve().parent / "_data"
_HISTORY_FILE = _DATA_DIR / "history.json"
_MAX_ENTRIES = int(os.environ.get("WS_HISTORY_MAX", "10"))

_lock = threading.RLock()
_entries: List[Dict[str, Any]] = []
_next_id: int = 1


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
    """Add a new history entry. Trims to _MAX_ENTRIES oldest-first."""
    global _next_id
    with _lock:
        _load()
        new_entry = {"id": _next_id, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                     **entry}
        _next_id += 1
        _entries.append(new_entry)
        # Trim from the front if over capacity
        while len(_entries) > _MAX_ENTRIES:
            _entries.pop(0)
        _save()
        return new_entry["id"]


def list_entries() -> List[Dict[str, Any]]:
    """Return entries newest-first (most recent at index 0)."""
    with _lock:
        _load()
        return list(reversed(_entries))


def get(entry_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        _load()
        for e in _entries:
            if e["id"] == entry_id:
                return e
        return None


def clear() -> None:
    global _next_id
    with _lock:
        _entries = []
        _next_id = 1
        if _HISTORY_FILE.exists():
            _HISTORY_FILE.unlink()