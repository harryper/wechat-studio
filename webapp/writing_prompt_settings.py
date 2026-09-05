"""Private persistence and rendering for the reusable writing Prompt template."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

from toolkit import env_config
from scripts.write_article import _build_outline, _load_client_context


WRITING_PROMPT_PATH = env_config.SKILL_DIR / "webapp" / "_data" / "writing-prompt.json"
PROMPT_LIMIT = 40_000
_SCHEMA_VERSION = 1

DEFAULT_PROMPT_TEMPLATE = """你是「微信公众号·知识科普」专栏的撰稿人，正在为一篇深度科普长文打底。请按 Markdown 输出正文，禁止任何额外评论。

主题信息：
- 主题 ID：user-input
- 主题标题：{{文章主题}}
- 分类：{{文章分类}}
- 起源/背景：{{背景资料}}
- 关键要点：
{{关键要点}}

使用的写作框架：
{{写作框架}}

写作要求：
- 全文 2500-4000 中文字（不含标点）
- 标题：学术定义式，30-50 字，可带副标题
- 摘要：约 100 字，点题即可
- 语气：academic but readable — 避免大段术语堆砌，避免空洞排比
- 引用经典文献/实验时给出人物、年份、方法名；不要编造具体数据
- 不需要加任何插图占位符，图片由后续流程单独插入
- 不需要写免责声明 — 由系统统一注入（"本文为逻辑梳理，非学术研究"）
- 注意：{{注意事项}}
{{客户风格}}

直接输出 Markdown 正文，开头是 `# 标题`，中间用 ## 切分章节。不要任何开场白或收尾评论。"""


def _validate_prompt(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Prompt 不能为空")
    if len(value) > PROMPT_LIMIT:
        raise ValueError(f"Prompt 不能超过 {PROMPT_LIMIT} 字")
    return value


def load_prompt(path: Optional[Path] = None) -> str:
    """Return the saved template, or the system default when none is saved."""
    source = Path(path or WRITING_PROMPT_PATH)
    if not source.exists():
        return DEFAULT_PROMPT_TEMPLATE
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Prompt 设置文件版本不受支持")
    return _validate_prompt(payload.get("prompt"))


def save_prompt(prompt: object, path: Optional[Path] = None) -> str:
    """Validate and atomically save a private reusable Prompt template."""
    validated = _validate_prompt(prompt)
    destination = Path(path or WRITING_PROMPT_PATH)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    temp_path: Optional[str] = None
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {"schema_version": _SCHEMA_VERSION, "prompt": validated},
                handle,
                ensure_ascii=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
    return validated


def render_prompt(
    template: str, topic: Mapping[str, Any], client: Optional[str] = None
) -> str:
    """Inject current article context into a saved Prompt template."""
    key_points = topic.get("key_points") or []
    points_text = "\n".join(f"- {point}" for point in key_points) or "-（暂无）"
    origin = str(topic.get("origin") or "（暂无）").strip()
    caution_note = (
        "该主题在公共传播中存在大量简化版本，请围绕原始文献/经典来源写作，避免给出未经验证的轶事。"
        if topic.get("caution") == "yes"
        else "无需特别警示，按主题本身的张力展开。"
    )
    client_context = _load_client_context(client)
    replacements = {
        "{{文章主题}}": str(topic.get("title") or ""),
        "{{文章分类}}": str(topic.get("category") or ""),
        "{{背景资料}}": origin,
        "{{关键要点}}": points_text,
        "{{写作框架}}": _build_outline(dict(topic)),
        "{{注意事项}}": caution_note,
        "{{客户风格}}": client_context,
    }
    rendered = _validate_prompt(template)
    has_client_marker = "{{客户风格}}" in rendered
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    if client_context and not has_client_marker:
        rendered = rendered.rstrip() + "\n\n" + client_context
    return rendered
