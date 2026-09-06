"""Local file-backed article history.

Data lives in ``_DATA_DIR / "history.json"``.  The file holds a monotonically
increasing ``next_id`` and an ``entries`` list.  Markdown content is never
stored in the index — ``get()`` reads it from the workdir's ``article.md``.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .local_store import AtomicStore

_DATA_DIR = Path(os.environ.get("WS_DATA_DIR", Path(__file__).resolve().parent / "_data"))
_HISTORY_PATH = _DATA_DIR / "history.json"

_EMPTY = {"next_id": 1, "entries": []}

_store = AtomicStore(_HISTORY_PATH, default=lambda: copy.deepcopy(_EMPTY))

IMMUTABLE_KEYS = {"id", "created_at"}


def _init_store(path: Optional[Path] = None) -> None:
    """Re-point the store (used by tests to isolate data)."""
    global _store, _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
    _store = AtomicStore(_HISTORY_PATH, default=lambda: copy.deepcopy(_EMPTY))


def add(entry: Dict[str, Any]) -> int:
    now = datetime.now(timezone.utc).isoformat()

    def _do_add(data):
        entry_id = data["next_id"]
        data["next_id"] = entry_id + 1
        record = {
            "id": entry_id,
            "created_at": now,
            "updated_at": now,
            **entry,
        }
        record.setdefault("status", "generating")
        record.setdefault("workdir", "")
        record.setdefault("image_mode", "placeholder")
        record.setdefault("assessment", {})
        data["entries"].append(record)
        return data

    _store.update(_do_add)
    return _store.read()["next_id"] - 1


def get(entry_id: int) -> Optional[Dict[str, Any]]:
    data = _store.read()
    for entry in data["entries"]:
        if entry["id"] == entry_id:
            result = copy.deepcopy(entry)
            workdir = result.get("workdir")
            if workdir:
                md_path = Path(workdir) / "article.md"
                if md_path.exists():
                    result["markdown"] = md_path.read_text(encoding="utf-8")
                else:
                    result["markdown"] = ""
            else:
                result["markdown"] = ""
            return result
    return None


def list_entries(*, status: str = "", query: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    data = _store.read()
    result = []
    for entry in reversed(data["entries"]):
        if status and entry.get("status") != status:
            continue
        if query and query not in entry.get("title", "") and query not in entry.get("topic_id", ""):
            continue
        item = copy.deepcopy(entry)
        item.pop("markdown", None)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def update(entry_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    safe = {k: v for k, v in changes.items() if k not in IMMUTABLE_KEYS}
    safe["updated_at"] = datetime.now(timezone.utc).isoformat()
    safe.pop("markdown", None)

    updated_entry = None

    def _do_update(data):
        nonlocal updated_entry
        for entry in data["entries"]:
            if entry["id"] == entry_id:
                entry.update(safe)
                updated_entry = copy.deepcopy(entry)
                break
        return data

    _store.update(_do_update)
    return updated_entry


def delete(entry_id: int) -> bool:
    found = False

    def _do_delete(data):
        nonlocal found
        before = len(data["entries"])
        data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]
        found = len(data["entries"]) < before
        return data

    _store.update(_do_delete)
    return found


def clear() -> None:
    """Remove all entries. For tests only — production uses cascade delete."""
    _store.write(copy.deepcopy(_EMPTY))
