#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wechat-studio Web 后端

微信公众号工作台，提供：
  - APP_PASSWORD 鉴权（HMAC cookie，30 天）
  - 主题 ID → 渲染预览（iframe srcdoc）
  - 推送按钮 → 同步调用 toolkit/cli.py publish

数据流：
  1. 浏览器 POST /api/preview  →  load corpus yaml → synthesize md → subprocess cli.py preview → 返回 HTML
  2. 浏览器 POST /api/publish  →  synthesize md → subprocess cli.py publish → 返回 stdout/stderr

cli.py 通过 config.yaml 读取 WECHAT_APPID / WECHAT_SECRET（已由 ${VAR}
占位符展开），所以这里不需要把密钥再传一次。
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Flask, jsonify, redirect, render_template, request

from .synthesize import synthesize_markdown

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

# cli.py 子进程超时（秒）。preview 通常 < 5s，publish 含外网上传 60s 足够。
SUBPROCESS_TIMEOUT = int(os.environ.get("SUBPROCESS_TIMEOUT", "60"))

# ── Flask 应用 ───────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_AS_ASCII"] = False
# 单用户 / 单容器：允许模板热重载（开发期方便观察改动）
app.config["TEMPLATES_AUTO_RELOAD"] = True


# ── 工具函数 ─────────────────────────────────────────────────────────
def _load_corpus() -> List[Dict[str, Any]]:
    """读取知识库语料。文件不存在时返回空列表而不是抛异常 — 让 /api/health 仍可工作。"""
    if not CORPUS_PATH.exists():
        return []
    try:
        with open(CORPUS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or []
    except (yaml.YAMLError, OSError) as e:
        print(f"[wechat-studio] failed to load corpus: {e}", file=sys.stderr)
        return []


def _find_topic(topic_id: str) -> Optional[Dict[str, Any]]:
    for t in _load_corpus():
        if t.get("id") == topic_id:
            return t
    return None


def _run_cli(args: List[str], env: Dict[str, str]) -> Dict[str, Any]:
    """同步调用 toolkit/cli.py 并返回结构化结果。

    cwd=SKILL_DIR 是关键：cli.py 的 CONFIG_PATHS 会先看 CWD/config.yaml，
    bind-mount 模式下 dev 容器里 CWD 与本机一致。env=os.environ 显式透传
    WECHAT_APPID / WECHAT_SECRET 等敏感变量，不依赖隐式继承。
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(TOOLKIT_DIR / "cli.py"), *args],
            cwd=str(SKILL_DIR),
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
    """未登录请求一律拒之门外。/login 和 /api/health 是公开的。

    - 浏览器访问任意页面 → 302 重定向到 /login
    - API 调用未带 cookie → 401 JSON
    """
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
        print(f"[wechat-studio] failed to list themes: {e}", file=sys.stderr)
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
            "version": "1.0.0",
            "corpus_size": len(_load_corpus()),
        }
    )


@app.route("/api/preview", methods=["POST"])
def api_preview():
    """Body: {topic_id, theme} → synthesize md → cli preview → HTML."""
    data = request.get_json(force=True, silent=True) or {}
    topic_id = (data.get("topic_id") or "").strip()
    theme = (data.get("theme") or "terracotta").strip() or "terracotta"

    if not topic_id:
        return jsonify({"ok": False, "error": "topic_id 不能为空"}), 400

    topic = _find_topic(topic_id)
    if not topic:
        return jsonify({"ok": False, "error": f"未找到主题 {topic_id}"}), 404

    md_text = synthesize_markdown(topic)
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "article.md"
        html_path = Path(tmpdir) / "article.html"
        md_path.write_text(md_text, encoding="utf-8")
        result = _run_cli(
            [
                "preview",
                str(md_path),
                "--theme",
                theme,
                "--no-open",
                "-o",
                str(html_path),
            ],
            env=os.environ.copy(),
        )
        if not result["ok"] or not html_path.exists():
            return jsonify(
                {
                    "ok": False,
                    "error": "预览生成失败",
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "returncode": result["returncode"],
                }
            ), 500
        html = html_path.read_text(encoding="utf-8")

    return jsonify(
        {
            "ok": True,
            "html": html,
            "topic": {
                "id": topic.get("id"),
                "title": topic.get("title"),
                "category": topic.get("category"),
            },
            "theme": theme,
        }
    )


@app.route("/api/publish", methods=["POST"])
def api_publish():
    """Body: {topic_id, theme, client} → synthesize md → cli publish → stdout/stderr。

    注意：这里不向 cli.py 传 --appid/--secret — 让 config.yaml 的 ${VAR}
    占位符展开流程（已在本机 env 中提供 WECHAT_APPID / WECHAT_SECRET）
    完成凭证注入。client 参数是历史命名空间，cli.py publish 暂不消费它，
    但前端仍带上以便后续扩展（例如 --author 按 client 路由）。
    """
    data = request.get_json(force=True, silent=True) or {}
    topic_id = (data.get("topic_id") or "").strip()
    theme = (data.get("theme") or "terracotta").strip() or "terracotta"
    client = (data.get("client") or "zhulv").strip() or "zhulv"

    if not topic_id:
        return jsonify({"ok": False, "error": "topic_id 不能为空"}), 400

    topic = _find_topic(topic_id)
    if not topic:
        return jsonify({"ok": False, "error": f"未找到主题 {topic_id}"}), 404

    md_text = synthesize_markdown(topic)
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "article.md"
        md_path.write_text(md_text, encoding="utf-8")
        # 切到临时目录作为 cwd 父级 — cli.py 解析相对图片路径时会用
        # md 文件所在目录，避免污染 SKILL_DIR。
        publish_cwd = tmpdir
        old_cwd = os.getcwd()
        try:
            os.chdir(publish_cwd)
            result = _run_cli(
                ["publish", str(md_path), "--theme", theme],
                env=os.environ.copy(),
            )
        finally:
            os.chdir(old_cwd)

    return jsonify(
        {
            "ok": result["ok"],
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "topic": {
                "id": topic.get("id"),
                "title": topic.get("title"),
            },
            "theme": theme,
            "client": client,
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
    print(f"[wechat-studio] 500: {e}\n{traceback.format_exc()}", file=sys.stderr)
    return jsonify({"error": "internal server error"}), 500


# ── 入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9997"))
    print(f"[wechat-studio] starting on :{port}, SKILL_DIR={SKILL_DIR}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
