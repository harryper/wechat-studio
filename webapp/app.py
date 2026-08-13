#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wechat-studio Web 后端

微信公众号工作台，提供：
  - APP_PASSWORD 鉴权（HMAC cookie，30 天）
  - 主题选择 → LLM 写文章 + 配图 → 渲染预览
  - 历史记录（最近 N 条，持久化到 webapp/_data/history.json）
  - 推送按钮 → cli.py publish

数据流：
  1. POST /api/jobs             → 返回 job_id，后台写作 + 5 张图 + 排版
  2. GET  /api/jobs/<id>        → 轮询阶段、进度和结果
  3. GET/PUT article/theme      → 在线编辑和换主题
  4. POST regenerate            → 异步重写文章或重生图片
  5. GET preflight             → Blacklist、AI 痕迹、标题和图片检查
  6. POST /api/publish          → 检查通过后用 workdir 创建微信草稿

cli.py 通过 config.yaml 读取 WECHAT_APPID / WECHAT_SECRET（已由 ${VAR}
占位符展开），所以这里不需要把密钥再传一次。
"""

import hashlib
import hmac
import logging
import os
import re
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Flask, Response, jsonify, redirect, render_template, request

from . import history, jobs, pipeline
from .render import (
    _write_preview_html,
)

# ── 路径常量 ─────────────────────────────────────────────────────────
# webapp/app.py → 父目录即 skill 根
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"
CORPUS_PATH = SKILL_DIR / "references" / "knowledge-corpus.yaml"
VERSION = (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()

# ── 访问鉴权 ─────────────────────────────────────────────────────────
APP_PASSWORD = os.environ.get("APP_PASSWORD", "asdf123456")
COOKIE_NAME = "ws_auth"
COOKIE_SECRET = os.environ.get("APP_COOKIE_SECRET", "wechat-studio-cookie-secret")
COOKIE_VALUE = hmac.new(
    COOKIE_SECRET.encode(), APP_PASSWORD.encode(), hashlib.sha256
).hexdigest()
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天

# 公开端点：登录页和健康检查。静态资源在 /static 前缀。
PUBLIC_PATHS = {"/login", "/api/health"}

# cli.py 子进程超时（秒）。publish 含外网上传 60s 足够。
SUBPROCESS_TIMEOUT = int(os.environ.get("SUBPROCESS_TIMEOUT", "60"))
JOB_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("WS_JOB_WORKERS", "1")),
    thread_name_prefix="wechat-studio-job",
)

# ── Flask 应用 ───────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_AS_ASCII"] = False
# 单用户 / 单容器：允许模板热重载（开发期方便观察改动）
app.config["TEMPLATES_AUTO_RELOAD"] = True

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wechat-studio")


# ── 工具函数 ─────────────────────────────────────────────────────────
def _load_corpus() -> List[Dict[str, Any]]:
    """读取知识库语料。文件不存在时返回空列表而不是抛异常 — 让 /api/health 仍可工作。"""
    if not CORPUS_PATH.exists():
        return []
    try:
        with open(CORPUS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or []
    except (yaml.YAMLError, OSError) as e:
        log.error("failed to load corpus: %s", e)
        return []


def _find_topic(topic_id: str) -> Optional[Dict[str, Any]]:
    for t in _load_corpus():
        if t.get("id") == topic_id:
            return t
    return None


def _run_cli(args: List[str], env: Dict[str, str],
             cwd: Optional[str] = None) -> Dict[str, Any]:
    """同步调用 toolkit/cli.py 并返回结构化结果。

    cwd 默认 SKILL_DIR；publish 路径在调用方手动 chdir 到 workdir 以保留
    历史行为（见 api_publish 注释）。
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(TOOLKIT_DIR / "cli.py"), *args],
            cwd=cwd or str(SKILL_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": e.stdout or "",
            "stderr": f"[timeout after {SUBPROCESS_TIMEOUT}s] {(e.stderr or '').strip()}",
        }
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


# ── 鉴权钩子 ─────────────────────────────────────────────────────────
@app.before_request
def require_auth():
    """未登录请求一律拒之门外。/login 和 /api/health 是公开的。"""
    if (
        request.path in PUBLIC_PATHS
        or request.path.startswith("/static/")
    ):
        return None
    expected = request.cookies.get(COOKIE_NAME)
    if expected and hmac.compare_digest(expected, COOKIE_VALUE):
        return None
    if request.path.startswith("/api/") or request.path.startswith("/__internal/"):
        return jsonify({"error": "unauthorized"}), 401
    return redirect("/login")


# ── 路由 ─────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    """登录页 / 登录提交。"""
    error = None
    if request.method == "POST":
        password = (request.form.get("password") or "").strip()
        if password and hmac.compare_digest(password, APP_PASSWORD):
            resp = redirect("/")
            resp.set_cookie(
                COOKIE_NAME,
                COOKIE_VALUE,
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                samesite="Lax",
                path="/",
            )
            return resp
        error = "密码错误"
    return render_template("login.html", error=error), (401 if error else 200)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    resp = redirect("/login")
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.route("/")
def index():
    # 把可用主题和语料列表注入页面，避免前端硬编码。
    try:
        sys.path.insert(0, str(TOOLKIT_DIR))
        from theme import list_themes  # type: ignore
        themes = list_themes()
    except Exception as e:
        log.error("failed to list themes: %s", e)
        themes = ["terracotta"]
    topics = [
        {"id": t.get("id"), "title": t.get("title"), "category": t.get("category")}
        for t in _load_corpus()
        if t.get("id")
    ]
    clients_dir = SKILL_DIR / "clients"
    clients = sorted(
        p.name for p in clients_dir.iterdir()
        if p.is_dir() and (p / "style.yaml").exists()
    ) if clients_dir.exists() else []
    return render_template("index.html", themes=themes, topics=topics, clients=clients)


@app.route("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "app": "wechat-studio",
            "version": VERSION,
            "corpus_size": len(_load_corpus()),
            "history_count": len(history.list_entries()),
        }
    )


@app.route("/api/jobs", methods=["POST"])
@app.route("/api/preview", methods=["POST"])
def api_create_job():
    """Queue a full generation job and return immediately with a job id."""
    data = request.get_json(force=True, silent=True) or {}
    topic_id = (data.get("topic_id") or "").strip()
    theme = (data.get("theme") or "terracotta").strip() or "terracotta"
    client = (data.get("client") or "").strip()

    if not topic_id:
        return jsonify({"ok": False, "error": "topic_id 不能为空",
                        "phase": "input"}), 400

    topic = _find_topic(topic_id)
    if not topic:
        return jsonify({"ok": False, "error": f"未找到主题 {topic_id}",
                        "phase": "input"}), 404

    if client and not re.fullmatch(r"[A-Za-z0-9_-]+", client):
        return jsonify({"ok": False, "error": "客户名格式不合法", "phase": "input"}), 400
    job = jobs.create("full", {"topic": topic, "theme": theme, "client": client})
    JOB_EXECUTOR.submit(pipeline.run_job, job["id"])
    return jsonify({"ok": True, "job_id": job["id"], "status": "queued"}), 202


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_job_get(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    return jsonify({"ok": True, "job": job})


# ── 历史记录 ──────────────────────────────────────────────────────────
@app.route("/api/history", methods=["GET"])
def api_history_list():
    """返回最近 N 条预览（最新在前），HTML 通过独立端点加载。"""
    return jsonify(
        {
            "ok": True,
            "entries": [
                {k: v for k, v in e.items() if k != "html"}
                for e in history.list_entries()
            ],
        }
    )


@app.route("/api/history/<int:entry_id>", methods=["GET"])
def api_history_get(entry_id: int):
    """Return entry metadata + iframe URL (no html — too big to ship in JSON)."""
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    return jsonify(
        {
            "ok": True,
            "entry": entry,
            "html_url": f"/api/history/{entry_id}/html",
        }
    )


@app.route("/api/history/<int:entry_id>/article", methods=["GET", "PUT"])
def api_history_article(entry_id: int):
    """Load or save editable Markdown; saving also refreshes the preview."""
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    md_path = Path(entry["workdir"]) / "article.md"
    if not md_path.exists():
        return jsonify({"ok": False, "error": "article.md 已丢失"}), 410
    if request.method == "GET":
        return jsonify({"ok": True, "markdown": md_path.read_text(encoding="utf-8")})

    data = request.get_json(force=True, silent=True) or {}
    markdown = data.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return jsonify({"ok": False, "error": "markdown 不能为空"}), 400
    if len(markdown.encode("utf-8")) > 512_000:
        return jsonify({"ok": False, "error": "markdown 超过 512KB"}), 413
    previous_markdown = md_path.read_text(encoding="utf-8")
    md_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    try:
        _write_preview_html(Path(entry["workdir"]), entry["theme"])
        assessment = pipeline.assess_markdown(markdown, entry.get("client") or None)
        updated = history.update(entry_id, {
            "title": assessment["title"] or entry.get("title"),
            "assessment": assessment,
        })
    except Exception as exc:
        md_path.write_text(previous_markdown, encoding="utf-8")
        return jsonify({"ok": False, "error": f"重新渲染失败：{exc}"}), 500
    return jsonify({"ok": True, "entry": updated, "html_url": f"/api/history/{entry_id}/html"})


@app.route("/api/history/<int:entry_id>/theme", methods=["PUT"])
def api_history_theme(entry_id: int):
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    theme = (data.get("theme") or "").strip()
    if not theme:
        return jsonify({"ok": False, "error": "theme 不能为空"}), 400
    try:
        _write_preview_html(Path(entry["workdir"]), theme)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"主题渲染失败：{exc}"}), 500
    updated = history.update(entry_id, {"theme": theme})
    return jsonify({"ok": True, "entry": updated, "html_url": f"/api/history/{entry_id}/html"})


@app.route("/api/history/<int:entry_id>/regenerate", methods=["POST"])
def api_history_regenerate(entry_id: int):
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    topic = _find_topic(entry.get("topic_id", ""))
    if topic is None:
        return jsonify({"ok": False, "error": "原知识库主题已不存在"}), 410
    data = request.get_json(force=True, silent=True) or {}
    kind = (data.get("stage") or "").strip()
    if kind not in {"article", "images", "image"}:
        return jsonify({"ok": False, "error": "stage 必须是 article/images/image"}), 400
    payload = {"history_id": entry_id, "topic": topic}
    if kind == "image":
        role = (data.get("role") or "").strip()
        if role not in {"cover", "inline-1", "inline-2", "inline-3", "inline-4"}:
            return jsonify({"ok": False, "error": "图片 role 不合法"}), 400
        payload["role"] = role
    job = jobs.create(kind, payload)
    JOB_EXECUTOR.submit(pipeline.run_job, job["id"])
    return jsonify({"ok": True, "job_id": job["id"], "status": "queued"}), 202


@app.route("/api/history/<int:entry_id>/preflight", methods=["GET"])
def api_history_preflight(entry_id: int):
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    return jsonify({"ok": True, **pipeline.preflight(entry)})


# MIME types for /api/history/<id>/images/
_HISTORY_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif",
}


@app.route("/api/history/<int:entry_id>/html", methods=["GET"])
def api_history_html(entry_id: int):
    """Serve the themed HTML for iframe.src.

    The HTML has relative <img src="images/cover.jpg"> references that
    resolve to /api/history/<id>/images/cover.jpg via the iframe's base URL.
    Article edits and theme changes can re-render the same history id, so the
    response is private but explicitly revalidated.
    """
    from .render import _inject_iframe_bootstrap  # local import keeps the webapp module-level surface tight

    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    html_path = Path(entry["workdir"]) / "article.html"
    if not html_path.exists():
        return jsonify({"ok": False, "error": "article.html 已丢失",
                        "phase": "session"}), 410
    html = _inject_iframe_bootstrap(html_path.read_text(encoding="utf-8"))
    resp = Response(html, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@app.route("/api/history/<int:entry_id>/images/<path:name>", methods=["GET"])
def api_history_image(entry_id: int, name: str):
    """Serve an image file from the workdir's images/ subdirectory.

    Rejects path-traversal: name must be a single segment without '/'.
    """
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    # Block path traversal: only accept a single filename, no slashes/dots.
    if "/" in name or ".." in name or name.startswith("."):
        return jsonify({"error": "bad image name"}), 400
    img_path = (Path(entry["workdir"]) / "images" / name).resolve()
    images_dir = (Path(entry["workdir"]) / "images").resolve()
    if not str(img_path).startswith(str(images_dir) + "/"):
        return jsonify({"error": "path escape"}), 400
    if not img_path.is_file():
        return jsonify({"error": "image not found"}), 404
    ext = img_path.suffix.lower()
    mime = _HISTORY_IMAGE_MIME.get(ext, "application/octet-stream")
    data = img_path.read_bytes()
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@app.route("/api/history/<int:entry_id>", methods=["DELETE"])
def api_history_delete(entry_id: int):
    """Delete a history entry and its workdir.

    The workdir is bind-mounted disk content — we own it and can free it.
    If the directory is already gone (cleanup is idempotent), that's fine.
    """
    import shutil

    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    history.delete(entry_id)
    workdir = entry.get("workdir")
    if workdir:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError as e:
            log.warning("failed to remove workdir %s: %s", workdir, e)
    log.info("deleted history #%d (workdir=%s)", entry_id, workdir)
    return jsonify({"ok": True, "deleted": entry_id})


# ── 推送 ─────────────────────────────────────────────────────────────
@app.route("/api/publish", methods=["POST"])
def api_publish():
    """Body: {history_id} → cli.py publish → stdout/stderr。

    必须传 history_id 而不是 topic_id — publish 只能跑在某次 preview 产
    出的 workdir 上（那里有 article.md + 本地图片路径，cli.py publish
    会自动上传图片到微信）。
    """
    data = request.get_json(force=True, silent=True) or {}
    history_id = data.get("history_id")
    if not isinstance(history_id, int):
        try:
            history_id = int(history_id)
        except (TypeError, ValueError):
            history_id = None

    if history_id is None:
        return jsonify({"ok": False, "error": "history_id 不能为空"}), 400

    entry = history.get(history_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{history_id} 不存在"}), 404

    workdir = Path(entry["workdir"])
    theme = entry["theme"]
    md_path = workdir / "article.md"
    if not md_path.exists():
        return jsonify({"ok": False,
                        "error": "article.md 缺失 — workdir 可能已被清理",
                        "phase": "session"}), 500

    readiness = pipeline.preflight(entry)
    if not readiness["publishable"]:
        return jsonify({
            "ok": False,
            "error": "发布前检查未通过",
            "phase": "preflight",
            "preflight": readiness,
        }), 409

    cli_result = _run_cli(
        ["publish", str(md_path), "--theme", theme],
        env=os.environ.copy(),
        cwd=str(workdir),
    )

    return jsonify(
        {
            "ok": cli_result["ok"],
            "returncode": cli_result["returncode"],
            "stdout": cli_result["stdout"],
            "stderr": cli_result["stderr"],
            "history_id": history_id,
            "topic": {
                "id": entry.get("topic_id"),
                "title": entry.get("title"),
            },
            "theme": theme,
            "preflight": readiness,
        }
    )


# ── 错误处理 ─────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return render_template("index.html"), 200


@app.errorhandler(500)
def server_error(e):
    log.error("500: %s\n%s", e, traceback.format_exc())
    return jsonify({"error": "internal server error"}), 500


# ── 入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9997"))
    log.info("starting on :%s, SKILL_DIR=%s", port, SKILL_DIR)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
