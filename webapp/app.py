#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wechat-studio Web 后端

微信公众号工作台，提供：
  - APP_PASSWORD 鉴权（HMAC cookie，30 天）
  - 主题选择 → LLM 写文章 + 配图 → 渲染预览
  - 历史记录（最近 N 条，持久化到 webapp/_data/history.json）
  - 推送按钮 → cli.py publish

数据流：
  1. POST /api/preview          → write_article (LLM) + 图片 + cli.py preview → HTML
  2. GET  /api/history          → 最近 N 条预览（最新在前）
  3. GET  /api/history/<id>     → 某条预览的元数据（html 不重发，按需走 /api/preview 重生成）
  4. POST /api/publish          → 用某条 history 的 workdir 跑 cli.py publish

cli.py 通过 config.yaml 读取 WECHAT_APPID / WECHAT_SECRET（已由 ${VAR}
占位符展开），所以这里不需要把密钥再传一次。
"""

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Flask, jsonify, redirect, render_template, request

from . import history
from .render import (
    generate_images_in_workdir,
    render_preview_html,
    write_article_to_workdir,
)

# ── 路径常量 ─────────────────────────────────────────────────────────
# webapp/app.py → 父目录即 skill 根
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"
CORPUS_PATH = SKILL_DIR / "references" / "knowledge-corpus.yaml"

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
    return render_template("index.html", themes=themes, topics=topics)


@app.route("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "app": "wechat-studio",
            "version": "1.3.0",
            "corpus_size": len(_load_corpus()),
            "history_count": len(history.list_entries()),
        }
    )


@app.route("/api/preview", methods=["POST"])
def api_preview():
    """Body: {topic_id, theme} → write_article + 图片 + cli preview → HTML。

    LLM 调用通常 30-180 秒；图片另加 10-30 秒（AI）或 <1 秒（占位图）。
    整个流程若超过 gunicorn 超时（默认 300s）会被 worker 回收并以 502/504 呈现。
    """
    data = request.get_json(force=True, silent=True) or {}
    topic_id = (data.get("topic_id") or "").strip()
    theme = (data.get("theme") or "terracotta").strip() or "terracotta"

    if not topic_id:
        return jsonify({"ok": False, "error": "topic_id 不能为空",
                        "phase": "input"}), 400

    topic = _find_topic(topic_id)
    if not topic:
        return jsonify({"ok": False, "error": f"未找到主题 {topic_id}",
                        "phase": "input"}), 404

    try:
        workdir, image_rels = write_article_to_workdir(topic)
    except RuntimeError as e:
        log.error("LLM write failed: %s", e)
        return jsonify({"ok": False, "error": str(e),
                        "phase": "write"}), 500

    try:
        image_mode = generate_images_in_workdir(workdir, topic, image_rels)
    except Exception as e:
        log.error("image generation hard-failed: %s", e)
        return jsonify({"ok": False, "error": f"图片生成失败：{e}",
                        "phase": "images"}), 500

    try:
        html = render_preview_html(workdir, theme)
    except Exception as e:
        log.error("preview render failed: %s", e)
        return jsonify({"ok": False, "error": f"预览渲染失败：{e}",
                        "phase": "render"}), 500

    entry_id = history.add({
        "topic_id": topic.get("id"),
        "title": topic.get("title", ""),
        "category": topic.get("category", ""),
        "theme": theme,
        "html": html,
        "workdir": str(workdir),
        "image_mode": image_mode,
    })
    log.info("preview %s → history #%d (%s, %d chars HTML)",
             topic_id, entry_id, image_mode, len(html))

    return jsonify(
        {
            "ok": True,
            "history_id": entry_id,
            "html": html,
            "image_mode": image_mode,
            "topic": {
                "id": topic.get("id"),
                "title": topic.get("title"),
                "category": topic.get("category"),
            },
            "theme": theme,
        }
    )


# ── 历史记录 ──────────────────────────────────────────────────────────
@app.route("/api/history", methods=["GET"])
def api_history_list():
    """返回最近 N 条预览（最新在前）。html 字段省略 — 详情走 /api/preview 重渲染或回看。"""
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
    """返回某条预览的完整 html + 元数据（用于「回看」按钮）。"""
    entry = history.get(entry_id)
    if entry is None:
        return jsonify({"ok": False, "error": f"history #{entry_id} 不存在"}), 404
    return jsonify({"ok": True, "entry": entry})


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

    # 切到 workdir 作为 cwd 父级 — cli.py 解析相对图片路径时使用
    # md 文件所在目录，避免污染 SKILL_DIR。
    old_cwd = os.getcwd()
    try:
        os.chdir(str(workdir))
        cli_result = _run_cli(
            ["publish", str(md_path), "--theme", theme],
            env=os.environ.copy(),
        )
    finally:
        os.chdir(old_cwd)

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