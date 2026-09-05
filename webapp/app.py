#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wechat-studio Web 后端

微信公众号工作台，提供：
  - APP_PASSWORD 鉴权（HMAC cookie，30 天）
  - 主题选择 → LLM 写文章 + 配图 → 渲染预览
  - D1 内容历史、任务状态和发布状态
  - 推送按钮 → cli.py publish

数据流：
  1. POST /api/jobs             → 返回 job_id，后台写作 + 5 张图 + 排版
  2. GET  /api/jobs/<id>        → 轮询阶段、进度和结果
  3. GET/PUT article/theme      → 在线编辑和换主题
  4. POST regenerate            → 异步重写文章或重生图片
  5. POST /api/publish          → 用户确认后用 workdir 创建微信草稿

cli.py 通过 config.yaml 读取 WECHAT_APPID / WECHAT_SECRET（已由 ${VAR}
占位符展开），所以这里不需要把密钥再传一次。
"""

import base64
import copy
import hashlib
import hmac
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, redirect, render_template, request
from PIL import Image

from toolkit.image_gen import generate_image_with_provider
from toolkit.llm_adapters import test_writing_connection
from toolkit.model_registry import (
    ProviderConfigError,
    get_provider,
    registry_payload,
    resolve_provider_config,
)
from toolkit.model_security import redact_sensitive
from . import (
    history,
    jobs,
    model_settings,
    pipeline,
    publications,
    topics,
    writing_prompt_settings,
)
from .d1_client import D1Error, client as d1
from .render import (
    _write_preview_html,
)

# ── 路径常量 ─────────────────────────────────────────────────────────
# webapp/app.py → 父目录即 skill 根
SKILL_DIR = Path(__file__).resolve().parent.parent
TOOLKIT_DIR = SKILL_DIR / "toolkit"
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
NO_STORE_PATHS = {
    "/",
    "/api/model-settings",
    "/api/model-settings/test-writing",
    "/api/model-settings/test-image",
    "/api/article-prompt",
    "/api/writing-prompt",
}

# cli.py 子进程超时（秒）。publish 含外网上传 60s 足够。
SUBPROCESS_TIMEOUT = int(os.environ.get("SUBPROCESS_TIMEOUT", "60"))
JOB_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("WS_JOB_WORKERS", "1")),
    thread_name_prefix="wechat-studio-job",
)

ARTICLE_SUBJECT_LIMIT = 120
ARTICLE_CATEGORY_LIMIT = 60
ARTICLE_ORIGIN_LIMIT = 2_000
ARTICLE_PROMPT_LIMIT = 40_000
ARTICLE_KEY_POINT_LIMIT = 500
ARTICLE_KEY_POINTS_LIMIT = 20
THEME_DISPLAY_NAMES = {
    "elegant-rose": "精致·玫瑰",
    "github": "GitHub 风格",
    "minimal": "极简",
    "professional-clean": "专业·清爽",
    "tech-modern": "科技·现代",
    "warm-editorial": "暖色·编辑",
}
WRITING_STYLE_PRODUCT_COPY = {
    "maoxuan": {
        "label": "现实思辨",
        "summary": "冷静、锋利、克制",
        "method": "观点明确，结合现实问题展开，减少概念堆砌",
    },
    "zhulv": {
        "label": "青年共鸣",
        "summary": "温暖、有态度、不说教",
        "method": "从真实感受与生活场景切入，用故事和情绪建立共鸣",
    },
}
DEFAULT_WRITING_STYLE = {
    "id": "",
    "label": "理性科普",
    "summary": "清晰、严谨、通俗易读",
    "suitable": "深度科普、概念解析、知识梳理",
    "method": "先解释概念，再梳理背景与关键问题，兼顾专业性和可读性",
    "avoid": "术语堆砌、空洞排比、未经验证的数据",
    "source": "通用默认",
}


def _writing_style_presets() -> list[dict[str, str]]:
    """Return product-facing copy for the available client style profiles."""
    import yaml

    presets = [DEFAULT_WRITING_STYLE.copy()]
    clients_dir = SKILL_DIR / "clients"
    if not clients_dir.exists():
        return presets
    for client_dir in sorted(path for path in clients_dir.iterdir() if path.is_dir()):
        style_path = client_dir / "style.yaml"
        product_copy = WRITING_STYLE_PRODUCT_COPY.get(client_dir.name)
        if not style_path.exists() or not product_copy:
            continue
        try:
            style = yaml.safe_load(style_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            log.warning("failed to load writing style %s: %s", client_dir.name, exc)
            continue
        topics = style.get("topics") if isinstance(style, dict) else []
        blacklist = style.get("blacklist") if isinstance(style, dict) else []
        presets.append({
            "id": client_dir.name,
            **product_copy,
            "suitable": "、".join(str(item) for item in (topics or [])[:3]),
            "avoid": "、".join(str(item) for item in (blacklist or [])),
            "source": str(style.get("name") or client_dir.name),
        })
    return presets


def _submit_model_job(job: dict, settings_snapshot: dict) -> None:
    """Queue a job with an isolated request-time model settings snapshot."""
    JOB_EXECUTOR.submit(pipeline.run_job, job["id"], copy.deepcopy(settings_snapshot))


def _article_text(
    data: dict,
    field: str,
    label: str,
    limit: Optional[int],
    *,
    default: str = "",
    preserve: bool = False,
) -> str:
    value = data.get(field, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本")
    if limit is not None and len(value) > limit:
        raise ValueError(f"{label}不能超过 {limit} 字")
    return value if preserve else value.strip()


def _article_form(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    key_points = data.get("key_points", [])
    if key_points is None:
        key_points = []
    if not isinstance(key_points, list):
        raise ValueError("关键要点格式不合法")
    if len(key_points) > ARTICLE_KEY_POINTS_LIMIT:
        raise ValueError(f"关键要点不能超过 {ARTICLE_KEY_POINTS_LIMIT} 条")
    cleaned_points = []
    for point in key_points:
        if not isinstance(point, str):
            raise ValueError("每条关键要点必须是文本")
        if len(point) > ARTICLE_KEY_POINT_LIMIT:
            raise ValueError(f"每条关键要点不能超过 {ARTICLE_KEY_POINT_LIMIT} 字")
        if point.strip():
            cleaned_points.append(point.strip())
    prompt_mode = _article_text(data, "prompt_mode", "Prompt 模式", 16, default="custom")
    if prompt_mode not in {"default", "custom", "template"}:
        raise ValueError("Prompt 模式必须是 default、custom 或 template")
    return {
        "subject": _article_text(data, "subject", "文章主题", ARTICLE_SUBJECT_LIMIT),
        "category": _article_text(
            data, "category", "分类", ARTICLE_CATEGORY_LIMIT, default="自定义主题"
        ) or "自定义主题",
        "origin": _article_text(data, "origin", "背景资料", ARTICLE_ORIGIN_LIMIT),
        "client": _article_text(data, "client", "客户名", 128),
        "prompt": _article_text(
            data,
            "prompt",
            "Prompt",
            ARTICLE_PROMPT_LIMIT if prompt_mode != "default" else None,
            preserve=True,
        ),
        "prompt_mode": prompt_mode,
        "key_points": cleaned_points,
    }

# ── Flask 应用 ───────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_AS_ASCII"] = False
# 单用户 / 单容器：允许模板热重载（开发期方便观察改动）
app.config["TEMPLATES_AUTO_RELOAD"] = True

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wechat-studio")


def _set_private_no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _model_settings_json(payload: dict, status: int = 200) -> Response:
    response = jsonify(payload)
    response.status_code = status
    return _set_private_no_store(response)


def _submitted_api_keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    sections = (value.get("writing"), value.get("image"), value)
    return tuple(
        api_key
        for section in sections
        if isinstance(section, dict)
        and isinstance((api_key := section.get("api_key")), str)
        and api_key
    )


def _settings_error(exc: object, submitted: object, status: int = 400) -> Response:
    return _model_settings_json(
        {
            "ok": False,
            "error": redact_sensitive(exc, secrets=_submitted_api_keys(submitted)),
        },
        status,
    )


@app.after_request
def prevent_sensitive_response_caching(response: Response) -> Response:
    """Keep secrets, generated prompts, and test results out of caches."""
    if request.path in NO_STORE_PATHS:
        return _set_private_no_store(response)
    return response


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
    # 把排版主题的产品名称、说明和配色一起注入页面，避免暴露内部文件名。
    try:
        sys.path.insert(0, str(TOOLKIT_DIR))
        from theme import list_themes, load_theme  # type: ignore
        themes = [
            {
                "id": theme_id,
                "name": THEME_DISPLAY_NAMES.get(theme_id, loaded.name),
                "description": loaded.description,
                "primary": loaded.colors.get("secondary") or loaded.colors.get("primary") or "#ff4d6d",
                "background": loaded.colors.get("background") or "#ffffff",
            }
            for theme_id in list_themes()
            for loaded in [load_theme(theme_id)]
        ]
    except Exception as e:
        log.error("failed to list themes: %s", e)
        themes = [{
            "id": "terracotta", "name": "赤陶", "description": "温暖克制的知识内容排版",
            "primary": "#C86442", "background": "#ffffff",
        }]
    writing_styles = _writing_style_presets()
    try:
        default_prompt = writing_prompt_settings.load_prompt()
    except Exception as exc:
        log.error("failed to load writing prompt: %s", exc)
        default_prompt = writing_prompt_settings.DEFAULT_PROMPT_TEMPLATE
    return render_template(
        "index.html",
        themes=themes,
        writing_styles=writing_styles,
        default_prompt=default_prompt,
    )


@app.route("/api/health")
def health():
    remote = d1.get("/health") or {}
    return jsonify(
        {
            "ok": True,
            "app": "wechat-studio",
            "version": VERSION,
            "storage": "d1",
            "corpus_size": remote.get("topics", 0),
            "history_count": remote.get("articles", 0),
            "job_count": remote.get("jobs", 0),
        }
    )


@app.route("/api/model-settings", methods=["GET", "PUT"])
def api_model_settings():
    """Return effective model settings or validate and persist a full form."""
    if request.method == "GET":
        try:
            effective = model_settings.load_effective_settings()
            settings = copy.deepcopy(effective.settings)
            for kind in ("writing", "image"):
                settings[kind].pop("adapter", None)
            return _model_settings_json({
                "ok": True,
                "registry": registry_payload(),
                "settings": settings,
                "source": effective.source,
                "warning": effective.warning,
            })
        except Exception as exc:
            return _settings_error(exc, None, 500)

    data = request.get_json(silent=True)
    submitted = data.get("settings") if isinstance(data, dict) else None
    try:
        validated = model_settings._validate_raw_settings(submitted)
        model_settings.save_settings(validated)
        return _model_settings_json({"ok": True, "settings": validated})
    except ProviderConfigError as exc:
        return _settings_error(exc, submitted)
    except Exception as exc:
        return _settings_error(exc, submitted, 500)


@app.route("/api/writing-prompt", methods=["GET", "PUT"])
def api_writing_prompt():
    """Load or persist the reusable writing Prompt template."""
    if request.method == "GET":
        try:
            return _model_settings_json({
                "ok": True,
                "prompt": writing_prompt_settings.load_prompt(),
                "system_default": writing_prompt_settings.DEFAULT_PROMPT_TEMPLATE,
            })
        except Exception as exc:
            return _model_settings_json({"ok": False, "error": str(exc)}, 500)

    data = request.get_json(silent=True)
    submitted = data.get("prompt") if isinstance(data, dict) else None
    try:
        saved = writing_prompt_settings.save_prompt(submitted)
        return _model_settings_json({"ok": True, "prompt": saved})
    except ValueError as exc:
        return _model_settings_json({"ok": False, "error": str(exc)}, 400)
    except Exception as exc:
        return _model_settings_json({"ok": False, "error": str(exc)}, 500)


@app.route("/api/model-settings/test-writing", methods=["POST"])
def api_model_settings_test_writing():
    """Test an unsaved writing form without mutating persisted settings."""
    data = request.get_json(silent=True)
    submitted = data.get("settings") if isinstance(data, dict) else None
    try:
        resolved = resolve_provider_config("writing", submitted)
        result = test_writing_connection(resolved)
        return _model_settings_json(result)
    except ProviderConfigError as exc:
        return _settings_error(exc, submitted)
    except Exception as exc:
        return _settings_error(exc, submitted, 502)


@app.route("/api/model-settings/test-image", methods=["POST"])
def api_model_settings_test_image():
    """Generate a temporary paid image and return only a bounded preview."""
    data = request.get_json(silent=True)
    submitted = data.get("settings") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("confirm_charge") is not True:
        return _model_settings_json(
            {"ok": False, "error": "测试会实际生成一张图片并产生费用，请确认后重试。"},
            400,
        )

    started_at = time.monotonic()
    try:
        resolved = resolve_provider_config("image", submitted)
        provider = get_provider("image", resolved["provider_id"])
        with tempfile.TemporaryDirectory(prefix="wechat-studio-image-test-") as temp_dir:
            original_path = Path(temp_dir) / "original.png"
            generate_image_with_provider(
                "一张简洁、中性的连接测试图片，不包含文字。",
                original_path,
                resolved,
                provider.test_size,
            )
            with Image.open(original_path) as original:
                original.thumbnail((512, 512))
                buffer = io.BytesIO()
                original.convert("RGB").save(buffer, format="JPEG", quality=85)
        image_data = base64.b64encode(buffer.getvalue()).decode("ascii")
        return _model_settings_json({
            "ok": True,
            "provider_id": resolved["provider_id"],
            "model": resolved["model"],
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            "image": f"data:image/jpeg;base64,{image_data}",
        })
    except ProviderConfigError as exc:
        return _settings_error(exc, submitted)
    except Exception as exc:
        return _settings_error(exc, submitted, 502)


@app.route("/api/topics", methods=["GET", "POST"])
def api_topics():
    """Search the topic center or create a custom topic."""
    if request.method == "GET":
        result = topics.list_topics(
            query=(request.args.get("q") or "").strip(),
            status=(request.args.get("status") or "available").strip(),
            category=(request.args.get("category") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            client_name=(request.args.get("client") or "").strip(),
        )
        return jsonify({"ok": True, **result})
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "主题标题不能为空"}), 400
    topic = topics.create_topic({
        "title": title,
        "category": (data.get("category") or "custom").strip() or "custom",
        "client": (data.get("client") or "").strip(),
        "source": "custom",
        "context": {
            "origin": (data.get("origin") or "").strip(),
            "key_points": data.get("key_points") or [],
            "caution": "no",
        },
    })
    return jsonify({"ok": True, "topic": topic}), 201


@app.route("/api/article-prompt", methods=["POST"])
def api_article_prompt():
    """Build the exact default writing prompt from unsaved form values."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        article = _article_form(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not article["subject"]:
        return jsonify({"ok": False, "error": "文章主题不能为空"}), 400
    client = article["client"]
    if client and not re.fullmatch(r"[A-Za-z0-9_-]+", client):
        return jsonify({"ok": False, "error": "客户名格式不合法"}), 400
    topic = {
        "id": "user-input",
        "title": article["subject"],
        "category": article["category"],
        "origin": article["origin"],
        "key_points": article["key_points"],
        "caution": "no",
    }
    template = article["prompt"] or writing_prompt_settings.load_prompt()
    return jsonify({
        "ok": True,
        "prompt": writing_prompt_settings.render_prompt(
            template, topic, client=client or None
        ),
    })


@app.route("/api/jobs", methods=["POST"])
@app.route("/api/preview", methods=["POST"])
def api_create_job():
    """Queue a full generation job and return immediately with a job id."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        article = _article_form(data)
        topic_id = _article_text(data, "topic_id", "topic_id", 200)
        theme = _article_text(data, "theme", "排版风格", 100, default="terracotta") or "terracotta"
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "phase": "input"}), 400
    subject = article["subject"]
    client = article["client"]
    prompt = article["prompt"]

    if not topic_id and not subject:
        return jsonify({"ok": False, "error": "文章主题不能为空",
                        "phase": "input"}), 400

    if client and not re.fullmatch(r"[A-Za-z0-9_-]+", client):
        return jsonify({"ok": False, "error": "客户名格式不合法", "phase": "input"}), 400
    if subject:
        category = article["category"]
        origin = article["origin"]
        cleaned_points = article["key_points"]
        prompt_topic = {
            "id": "user-input",
            "title": subject,
            "category": category,
            "origin": origin,
            "key_points": cleaned_points,
            "caution": "no",
        }
        if article["prompt_mode"] == "default" or not prompt.strip():
            prompt = writing_prompt_settings.render_prompt(
                writing_prompt_settings.load_prompt(),
                prompt_topic,
                client=client or None,
            )
        elif article["prompt_mode"] == "template":
            prompt = writing_prompt_settings.render_prompt(
                prompt, prompt_topic, client=client or None
            )
        topic = topics.create_topic({
            "title": subject,
            "category": category,
            "client": client,
            "source": "custom",
            "context": {
                "origin": origin,
                "key_points": cleaned_points,
                "caution": "no",
                "prompt": prompt,
            },
        })
    else:
        topic = topics.get_topic(topic_id)
        if not topic:
            return jsonify({"ok": False, "error": f"未找到主题 {topic_id}",
                            "phase": "input"}), 404
    settings_snapshot = model_settings.snapshot_settings()
    entry_id = history.add({
        "topic_id": topic["id"],
        "title": topic["title"],
        "category": topic.get("category", ""),
        "theme": theme,
        "client": client,
        "status": "generating",
    })
    try:
        job = jobs.create("full", {
            "topic": topic,
            "theme": theme,
            "client": client,
            "prompt": prompt,
            "history_id": entry_id,
            "models": model_settings.audit_settings(settings_snapshot),
        })
    except Exception:
        history.update(entry_id, {"status": "failed"})
        raise
    _submit_model_job(job, settings_snapshot)
    return jsonify({"ok": True, "job_id": job["id"], "history_id": entry_id, "status": "queued"}), 202


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
    if request.method == "GET":
        markdown = entry.get("markdown")
        if not markdown:
            return jsonify({"ok": False, "error": "D1 中没有正文内容"}), 410
        return jsonify({"ok": True, "markdown": markdown})
    md_path = Path(entry["workdir"]) / "article.md"
    if not md_path.exists():
        return jsonify({"ok": False, "error": "本地排版产物已丢失"}), 410

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
        title = pipeline.extract_title(markdown)
        updated = history.update(entry_id, {
            "title": title or entry.get("title"),
            "markdown": markdown.rstrip() + "\n",
            "status": "draft",
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
    topic = topics.get_topic(entry.get("topic_id", ""))
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
    settings_snapshot = model_settings.snapshot_settings()
    payload["models"] = model_settings.audit_settings(settings_snapshot)
    previous_status = entry.get("status") or "draft"
    history.update(entry_id, {"status": "generating"})
    try:
        job = jobs.create(kind, payload)
    except Exception:
        history.update(entry_id, {"status": "failed", "details": {"previous_status": previous_status}})
        raise
    _submit_model_job(job, settings_snapshot)
    return jsonify({"ok": True, "job_id": job["id"], "status": "queued"}), 202


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

    cli_result = _run_cli(
        ["publish", str(md_path), "--theme", theme],
        env=os.environ.copy(),
        cwd=str(workdir),
    )

    media_match = re.search(r"Draft created! media_id:\s*(\S+)", cli_result["stdout"])
    publications.record(
        history_id,
        status="pushed" if cli_result["ok"] else "failed",
        remote_id=media_match.group(1) if media_match else None,
        response={
            "returncode": cli_result["returncode"],
            "stdout": cli_result["stdout"],
            "stderr": cli_result["stderr"],
        },
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


@app.errorhandler(D1Error)
def d1_error(e):
    log.error("D1 data service error: %s", e)
    return jsonify({"ok": False, "error": str(e), "phase": "storage"}), 502


# ── 入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9997"))
    log.info("starting on :%s, SKILL_DIR=%s", port, SKILL_DIR)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
