#!/usr/bin/env python3
"""Seed the D1 topic center and import legacy Web JSON state once."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.d1_client import D1Client  # noqa: E402


def _host_workdir(value: str) -> Path:
    prefix = "/app/webapp/"
    if value.startswith(prefix):
        return ROOT / "webapp" / value[len(prefix):]
    return Path(value)


def _markdown(entry: Dict[str, Any]) -> str:
    path = _host_workdir(entry.get("workdir") or "") / "article.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def seed_topics(api: D1Client) -> int:
    corpus = yaml.safe_load(
        (ROOT / "references" / "knowledge-corpus.yaml").read_text(encoding="utf-8")
    ) or []
    payload = api.post("/topics/bulk", {"topics": corpus})
    return int(payload.get("upserted", 0))


def import_history(api: D1Client) -> int:
    path = ROOT / "webapp" / "_data" / "history.json"
    if not path.exists():
        return 0
    entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    imported = 0
    for entry in sorted(entries, key=lambda item: int(item["id"])):
        existing = api.get(f"/articles/history/{entry['id']}", allow_404=True)
        if existing:
            continue
        api.post("/articles", {
            "local_history_id": int(entry["id"]),
            "topic_id": entry.get("topic_id"),
            "client": entry.get("client") or "",
            "title": entry.get("title") or "",
            "category": entry.get("category") or "",
            "status": "ready",
            "theme": entry.get("theme") or "terracotta",
            "markdown": _markdown(entry),
            "image_mode": entry.get("image_mode"),
            "assessment": entry.get("assessment") or {},
            "workdir": entry.get("workdir") or "",
            "created_at": entry.get("created_at"),
        })
        topic_id = entry.get("topic_id")
        if topic_id:
            api.patch(f"/topics/{topic_id}", {
                "status": "drafted",
                "details": {"migration": True, "history_id": int(entry["id"])},
            })
        imported += 1
    return imported


def import_jobs(api: D1Client) -> int:
    jobs_dir = ROOT / "webapp" / "_data" / "jobs"
    imported = 0
    for path in sorted(jobs_dir.glob("*.json")) if jobs_dir.exists() else []:
        job = json.loads(path.read_text(encoding="utf-8"))
        if api.get(f"/jobs/{job['id']}", allow_404=True):
            continue
        created = api.post("/jobs", {
            "id": job["id"],
            "kind": job["kind"],
            "payload": job.get("payload") or {},
            "history_id": (job.get("payload") or {}).get("history_id"),
        })["job"]
        final_status = job.get("status") or "failed"
        common = {
            "phase": job.get("phase") or final_status,
            "progress": int(job.get("progress") or 0),
            "result": job.get("result"),
            "error": job.get("error"),
        }
        if final_status in {"running", "completed"}:
            api.patch(f"/jobs/{created['id']}", {"status": "running", **common})
        if final_status == "completed":
            api.patch(f"/jobs/{created['id']}", {"status": "completed", **common})
        elif final_status not in {"queued", "running"}:
            api.patch(f"/jobs/{created['id']}", {"status": final_status, **common})
        imported += 1
    return imported


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--token-file", default=str(ROOT / ".d1_api_token"))
    args = parser.parse_args()
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    api = D1Client(args.api_url, token)
    print(f"topics={seed_topics(api)}")
    print(f"history={import_history(api)}")
    print(f"jobs={import_jobs(api)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
