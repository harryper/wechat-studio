import json
import os

import pytest

from scripts import write_article
from webapp import writing_prompt_settings


def test_save_is_atomic_private_and_loads_saved_template(tmp_path):
    path = tmp_path / "writing-prompt.json"
    template = "围绕 {{文章主题}} 写作，并覆盖：\n{{关键要点}}"

    saved = writing_prompt_settings.save_prompt(template, path)

    assert saved == template
    assert writing_prompt_settings.load_prompt(path) == template
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "prompt": template,
    }
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_returns_system_default_when_no_saved_file_exists(tmp_path):
    assert writing_prompt_settings.load_prompt(tmp_path / "missing.json") == (
        writing_prompt_settings.DEFAULT_PROMPT_TEMPLATE
    )


@pytest.mark.parametrize("value", ["", "   ", 123, None])
def test_save_rejects_empty_or_non_text_prompt(value, tmp_path):
    with pytest.raises(ValueError, match="Prompt"):
        writing_prompt_settings.save_prompt(value, tmp_path / "writing-prompt.json")


def test_render_prompt_injects_current_article_values():
    template = (
        "主题={{文章主题}}\n分类={{文章分类}}\n背景={{背景资料}}\n"
        "要点：\n{{关键要点}}\n框架：\n{{写作框架}}\n{{客户风格}}"
    )
    topic = {
        "id": "user-input",
        "title": "新的文章主题",
        "category": "效率工具",
        "origin": "用户访谈",
        "key_points": ["第一点", "第二点"],
        "caution": "no",
    }

    rendered = writing_prompt_settings.render_prompt(template, topic)

    assert "主题=新的文章主题" in rendered
    assert "分类=效率工具" in rendered
    assert "背景=用户访谈" in rendered
    assert "- 第一点\n- 第二点" in rendered
    assert "{{" not in rendered


def test_render_prompt_appends_selected_style_when_placeholder_is_missing(
    tmp_path, monkeypatch
):
    client_dir = tmp_path / "clients" / "demo"
    client_dir.mkdir(parents=True)
    (client_dir / "style.yaml").write_text(
        "tone: 冷静、锋利、克制\nvoice: 不端着，不喊口号\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(write_article, "SKILL_DIR", tmp_path)
    topic = {
        "title": "逆向思维",
        "category": "认知",
        "origin": "",
        "key_points": [],
        "caution": "no",
    }

    rendered = writing_prompt_settings.render_prompt(
        "请围绕 {{文章主题}} 写一篇文章。", topic, client="demo"
    )

    assert "请围绕 逆向思维 写一篇文章。" in rendered
    assert "客户风格" in rendered
    assert "冷静、锋利、克制" in rendered
    assert "不端着，不喊口号" in rendered
