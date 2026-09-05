"""Background article generation pipeline."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from toolkit.model_security import redact_sensitive

from . import history, jobs, topics
from .render import (
    _write_preview_html,
    ensure_default_image_references,
    generate_images_in_workdir,
    generate_single_image_in_workdir,
    write_article_to_workdir,
)


def extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""

def entry_result(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "history_id": entry["id"],
        "html_url": f"/api/history/{entry['id']}/html",
        "image_mode": entry.get("image_mode", "placeholder"),
        "topic": {
            "id": entry.get("topic_id"),
            "title": entry.get("title"),
            "category": entry.get("category"),
        },
        "theme": entry.get("theme"),
        "status": entry.get("status", "draft"),
    }


def run_job(job_id: str, settings_snapshot: dict) -> None:
    """Execute a queued full/regeneration job and persist every phase."""
    job = jobs.get(job_id)
    if job is None:
        return
    payload = job["payload"]
    kind = job["kind"]
    try:
        jobs.update(job_id, status="running", phase="starting", progress=5)
        if kind == "full":
            topic = payload["topic"]
            theme = payload["theme"]
            client = payload.get("client") or None
            prompt = payload.get("prompt") or topic.get("prompt") or None
            entry_id = int(payload["history_id"])
            jobs.update(job_id, phase="writing", progress=10)
            workdir, image_rels = write_article_to_workdir(
                topic,
                client=client,
                writing_settings=settings_snapshot["writing"],
                prompt=prompt,
            )
            jobs.update(job_id, phase="images", progress=45)
            image_mode = generate_images_in_workdir(
                workdir,
                topic,
                image_rels,
                settings_snapshot["image"],
            )
            jobs.update(job_id, phase="render", progress=85)
            _write_preview_html(workdir, theme)
            markdown = (workdir / "article.md").read_text(encoding="utf-8")
            entry = history.update(entry_id, {
                "title": extract_title(markdown) or topic.get("title", ""),
                "theme": theme,
                "workdir": str(workdir),
                "image_mode": image_mode,
                "markdown": markdown,
                "status": "draft",
            })
            if entry is None:
                raise RuntimeError(f"history #{entry_id} 不存在")
            topics.set_status(
                topic["id"],
                "drafted",
                {"history_id": entry_id, "job_id": job_id},
            )
        else:
            entry_id = int(payload["history_id"])
            entry = history.get(entry_id)
            if entry is None:
                raise RuntimeError(f"history #{entry_id} 不存在")
            topic = payload["topic"]
            workdir = Path(entry["workdir"])
            client = entry.get("client") or None
            if kind == "article":
                jobs.update(job_id, phase="writing", progress=15)
                write_article_to_workdir(
                    topic,
                    workdir=workdir,
                    client=client,
                    writing_settings=settings_snapshot["writing"],
                    prompt=topic.get("prompt") or None,
                )
                changes = {}
            elif kind == "images":
                jobs.update(job_id, phase="images", progress=20)
                image_rels = ensure_default_image_references(workdir)
                mode = generate_images_in_workdir(
                    workdir,
                    topic,
                    image_rels,
                    settings_snapshot["image"],
                )
                changes = {"image_mode": mode}
            elif kind == "image":
                jobs.update(job_id, phase="images", progress=20)
                mode = generate_single_image_in_workdir(
                    workdir,
                    topic,
                    payload["role"],
                    settings_snapshot["image"],
                )
                changes = {"image_mode": mode}
            else:
                raise RuntimeError(f"不支持的任务类型：{kind}")
            jobs.update(job_id, phase="render", progress=85)
            _write_preview_html(workdir, entry["theme"])
            markdown = (workdir / "article.md").read_text(encoding="utf-8")
            changes["markdown"] = markdown
            if kind == "article":
                changes["title"] = extract_title(markdown) or entry.get("title")
            changes["status"] = "draft"
            entry = history.update(entry_id, changes)
            if entry is None:
                raise RuntimeError(f"history #{entry_id} 不存在")

        if entry is None:
            raise RuntimeError("保存历史记录失败")
        jobs.update(
            job_id,
            status="completed",
            phase="completed",
            progress=100,
            result=entry_result(entry),
        )
    except Exception as exc:
        api_keys = (
            settings_snapshot["writing"]["api_key"],
            settings_snapshot["image"]["api_key"],
        )
        failed_history_id = (job.get("payload") or {}).get("history_id") if job else None
        if failed_history_id:
            try:
                history.update(int(failed_history_id), {"status": "failed"})
            except Exception:
                pass
        jobs.update(
            job_id,
            status="failed",
            phase=jobs.get(job_id).get("phase", "failed") if jobs.get(job_id) else "failed",
            error=redact_sensitive(
                f"{type(exc).__name__}: {exc}", secrets=api_keys
            ),
        )
