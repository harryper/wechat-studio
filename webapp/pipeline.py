"""Background generation pipeline and publish-readiness checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from scripts.check_blacklist import check as check_blacklist
from scripts.humanness_score import score_article
from toolkit.model_security import redact_sensitive

from . import history, jobs, topics
from .render import (
    _write_preview_html,
    ensure_default_image_references,
    generate_images_in_workdir,
    generate_single_image_in_workdir,
    write_article_to_workdir,
)


SKILL_DIR = Path(__file__).resolve().parent.parent


def extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _client_blacklist(client: Optional[str]) -> list[str]:
    if not client or not re.fullmatch(r"[A-Za-z0-9_-]+", client):
        return []
    path = SKILL_DIR / "clients" / client / "style.yaml"
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    return cfg.get("blacklist", []) or []


def assess_markdown(markdown: str, client: Optional[str] = None) -> Dict[str, Any]:
    title = extract_title(markdown)
    blacklist = check_blacklist(title, _client_blacklist(client))
    score = score_article(markdown).get("composite_score")
    return {
        "title": title,
        "blacklist": blacklist,
        "humanness_score": score,
        "client": client or "",
        "playbook_applied": bool(
            client and (SKILL_DIR / "clients" / client / "playbook.md").exists()
        ),
    }


def assess_workdir(workdir: Path, client: Optional[str] = None) -> Dict[str, Any]:
    return assess_markdown((workdir / "article.md").read_text(encoding="utf-8"), client)


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
        "assessment": entry.get("assessment", {}),
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
            entry_id = int(payload["history_id"])
            jobs.update(job_id, phase="writing", progress=10)
            workdir, image_rels = write_article_to_workdir(
                topic,
                client=client,
                writing_settings=settings_snapshot["writing"],
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
            jobs.update(job_id, phase="quality", progress=92)
            assessment = assess_workdir(workdir, client)
            markdown = (workdir / "article.md").read_text(encoding="utf-8")
            entry = history.update(entry_id, {
                "title": assessment["title"] or topic.get("title", ""),
                "theme": theme,
                "workdir": str(workdir),
                "image_mode": image_mode,
                "assessment": assessment,
                "markdown": markdown,
                "status": "draft",
            })
            if entry is None:
                raise RuntimeError(f"history #{entry_id} 不存在")
            readiness = preflight(entry)
            entry = history.update(
                entry_id,
                {"status": "ready" if readiness["publishable"] else "review"},
            )
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
                )
                assessment = assess_workdir(workdir, client)
                changes = {"title": assessment["title"] or entry.get("title"), "assessment": assessment}
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
            changes["markdown"] = (workdir / "article.md").read_text(encoding="utf-8")
            changes["status"] = "draft"
            entry = history.update(entry_id, changes)
            if entry is None:
                raise RuntimeError(f"history #{entry_id} 不存在")
            readiness = preflight(entry)
            entry = history.update(
                entry_id,
                {"status": "ready" if readiness["publishable"] else "review"},
            )

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
            error=(
                f"{type(exc).__name__}: "
                f"{redact_sensitive(exc, secrets=api_keys)}"
            ),
        )


def preflight(entry: Dict[str, Any]) -> Dict[str, Any]:
    workdir = Path(entry["workdir"])
    md_path = workdir / "article.md"
    if not md_path.exists():
        return {"publishable": False, "checks": [{"key": "article", "level": "error", "message": "article.md 缺失"}]}

    markdown = md_path.read_text(encoding="utf-8")
    assessment = assess_markdown(markdown, entry.get("client") or None)
    title = assessment["title"]
    refs = re.findall(r"!\[[^]]*\]\(([^)]+)\)", markdown)
    local_refs = [ref for ref in refs if not ref.startswith(("http://", "https://"))]
    missing = [ref for ref in local_refs if not (workdir / ref).is_file()]
    cover = next((ref for ref in refs if re.search(r"(?:^|/)cover\.(?:jpe?g|png|gif|webp)$", ref, re.I)), None)
    states_path = workdir / "image-status.json"
    try:
        image_states = json.loads(states_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        image_states = {}

    checks = [
        {"key": "title", "level": "pass" if title else "error", "message": f"标题：{title or '缺失'}"},
        {"key": "title_length", "level": "pass" if 20 <= len(title) <= 50 else "warn", "message": f"标题长度：{len(title)} 字（建议 20–50）"},
        {"key": "images", "level": "pass" if len(refs) >= 5 else "warn", "message": f"图片：{len(refs)} 张（目标 5 张）"},
        {"key": "missing_images", "level": "error" if missing else "pass", "message": f"缺失图片：{', '.join(missing)}" if missing else "图片文件完整"},
        {"key": "cover", "level": "pass" if cover else "error", "message": f"封面：{cover}" if cover else "未识别到 cover 图片"},
        {"key": "blacklist", "level": "pass" if assessment["blacklist"]["passed"] else "error", "message": "Blacklist 通过" if assessment["blacklist"]["passed"] else f"Blacklist 命中：{', '.join(h['pattern'] for h in assessment['blacklist']['hits'])}"},
        {"key": "humanness", "level": "warn" if (assessment["humanness_score"] or 0) >= 65 else "pass", "message": f"AI 痕迹分：{assessment['humanness_score']}/100（越低越自然）"},
        {"key": "disclaimer", "level": "pass", "message": "发布时将自动追加声明"},
    ]
    if image_states:
        placeholders = [role for role, state in image_states.items() if state != "real"]
        checks.append({
            "key": "image_mode",
            "level": "warn" if placeholders else "pass",
            "message": f"占位图：{', '.join(placeholders)}" if placeholders else "5 张图均为 AI 生成",
        })
    return {
        "publishable": not any(item["level"] == "error" for item in checks),
        "checks": checks,
        "assessment": assessment,
        "image_states": image_states,
    }
