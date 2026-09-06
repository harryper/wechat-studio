"""Topic center backed by knowledge-corpus.yaml and local topics.json.

Built-in topics are loaded from the YAML corpus each time.  User-created
custom topics are persisted in ``_DATA_DIR / "topics.json"``.  Both sets
are merged at query time.
"""

from __future__ import annotations

import copy
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .local_store import AtomicStore

_SKILL_DIR = Path(__file__).resolve().parent.parent
_CORPUS_PATH = _SKILL_DIR / "references" / "knowledge-corpus.yaml"
_DATA_DIR = Path(os.environ.get("WS_DATA_DIR", Path(__file__).resolve().parent / "_data"))
_TOPICS_PATH = _DATA_DIR / "topics.json"

_store = AtomicStore(_TOPICS_PATH, default=lambda: {"topics": {}})


def _init_store(path: Optional[Path] = None, corpus_path: Optional[Path] = None) -> None:
    """Re-point the store and corpus (used by tests)."""
    global _store, _TOPICS_PATH, _CORPUS_PATH
    if path is not None:
        _TOPICS_PATH = path
        _store = AtomicStore(_TOPICS_PATH, default=lambda: {"topics": {}})
    if corpus_path is not None:
        _CORPUS_PATH = corpus_path


def _load_corpus() -> Dict[str, Dict[str, Any]]:
    if not _CORPUS_PATH.exists():
        return {}
    try:
        items = yaml.safe_load(_CORPUS_PATH.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        return {}
    result = {}
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            continue
        result[item["id"]] = {
            "id": item["id"],
            "title": item.get("title", ""),
            "category": item.get("category", ""),
            "source": "corpus",
            "status": "available",
            "client": "",
            "context": {
                "origin": item.get("origin", ""),
                "key_points": item.get("key_points", []),
                "caution": item.get("caution", "no"),
                "prompt": "",
            },
        }
    return result


def _normalize(topic: Dict[str, Any]) -> Dict[str, Any]:
    context = topic.get("context") if isinstance(topic.get("context"), dict) else {}
    return {
        **topic,
        "key_points": context.get("key_points", []),
        "origin": context.get("origin", ""),
        "caution": context.get("caution", "no"),
        "prompt": context.get("prompt", ""),
    }


def _compute_status(topic_id: str) -> str:
    """Derive status from history: available if no articles reference this topic, drafted otherwise."""
    from . import history
    entries = history.list_entries(limit=500)
    for entry in entries:
        if entry.get("topic_id") == topic_id:
            return "drafted"
    return "available"


def _all_topics() -> Dict[str, Dict[str, Any]]:
    corpus = _load_corpus()
    custom = _store.read().get("topics", {})
    merged = {**corpus}
    for tid, topic in custom.items():
        merged[tid] = topic
    return merged


def list_topics(
    *,
    query: str = "",
    status: str = "available",
    category: str = "",
    source: str = "",
    client_name: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    all_topics = _all_topics()
    result = []
    for topic in all_topics.values():
        effective_status = _compute_status(topic["id"])
        if status and status != "all" and effective_status != status:
            continue
        if category and topic.get("category") != category:
            continue
        if source and topic.get("source") != source:
            continue
        if client_name and topic.get("client") != client_name:
            continue
        if query and query not in topic.get("title", "") and query not in topic.get("id", ""):
            continue
        item = _normalize(copy.deepcopy(topic))
        item["status"] = effective_status
        result.append(item)
        if len(result) >= limit:
            break
    return {"topics": result, "total": len(result)}


def get_topic(topic_id: str) -> Optional[Dict[str, Any]]:
    all_topics = _all_topics()
    topic = all_topics.get(topic_id)
    if topic is None:
        return None
    item = _normalize(copy.deepcopy(topic))
    item["status"] = _compute_status(topic_id)
    return item


def create_topic(data: Dict[str, Any]) -> Dict[str, Any]:
    topic_id = data.get("id") or f"custom-{uuid.uuid4()}"
    topic = {
        "id": topic_id,
        "title": data.get("title", ""),
        "category": data.get("category", "custom"),
        "source": data.get("source", "custom"),
        "status": "available",
        "client": data.get("client", ""),
        "context": data.get("context", {}),
    }

    def _do_create(store_data):
        store_data.setdefault("topics", {})
        store_data["topics"][topic_id] = topic
        return store_data

    _store.update(_do_create)
    return _normalize(copy.deepcopy(topic))
