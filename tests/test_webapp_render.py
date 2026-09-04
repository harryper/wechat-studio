"""Tests for webapp/render.py _write_preview_html CJK-spacing defense.

These tests guard against the historical bug where a previous webapp version
went through converter.py's legacy path (which inserts U+0020 between every
CJK pair), polluting article.html files with `可 得性`-style spacing.

The defense: after cli.py preview writes article.html, scan it for the
CJK+CJK space pattern. If found, re-render via xiaohu directly so the
output is clean regardless of which path cli.py used.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from webapp import render


CJK_PAIR_RE = re.compile(r"[一-鿿] [一-鿿]")
WRITING_SETTINGS = {
    "provider_id": "custom-openai",
    "adapter": "openai_compatible",
    "model": "writer",
    "base_url": "https://llm.example/v1",
    "api_key": "write-secret",
}
IMAGE_SETTINGS = {
    "provider_id": "cliproxy", "adapter": "openai", "model": "gpt-image-2",
    "base_url": "http://127.0.0.1:8317/v1", "api_key": "image-secret",
}
ARTICLE = "# 新标题\n\n## 摘要\n\n正文"


def _make_workdir(tmp_path: Path, article_md: str) -> Path:
    wd = tmp_path / "workdir"
    wd.mkdir()
    (wd / "article.md").write_text(article_md, encoding="utf-8")
    return wd


def test_write_article_to_workdir_forwards_writing_settings(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        render,
        "write_article",
        lambda topic, **kwargs: captured.update(kwargs) or ARTICLE,
    )

    render.write_article_to_workdir(
        {"title": "损失厌恶", "category": "认知偏差", "key_points": ["损失比同额收益更显著"]},
        tmp_path,
        writing_settings=WRITING_SETTINGS,
    )

    assert captured["settings"] == WRITING_SETTINGS


def test_write_preview_html_drops_legacy_cjk_cjk_spacing(tmp_path, monkeypatch):
    """If cli.py preview somehow produces a CJK-spaced article.html,
    _write_preview_html must re-render via xiaohu so the final file is clean.
    """
    workdir = _make_workdir(tmp_path, "# 测试\n\n可得性启发。\n")

    bad_html = (
        "<!DOCTYPE html><html><head><style>body{margin:0;padding:0;background:#f5f5f5}</style></head>"
        "<body><p>可 得性 启发。</p></body></html>"
    )
    clean_inner = '<section><p>可得性启发。</p></section>'

    def fake_run(cmd, **kwargs):
        # First call: cli.py preview with -o OUTPUT (bad_html)
        if "-o" in cmd:
            out = cmd[cmd.index("-o") + 1]
            Path(out).write_text(bad_html, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        # Second call: xiaohu fallback writes preview.html inside <stem>/ dir
        if "--output" in cmd:
            xiaohu_out_dir = Path(cmd[cmd.index("--output") + 1])
            stem = Path(cmd[cmd.index("--input") + 1]).stem
            target_dir = xiaohu_out_dir / stem
            target_dir.mkdir(exist_ok=True)
            (target_dir / "preview.html").write_text(clean_inner, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render.subprocess, "run", fake_run)
    monkeypatch.setattr(render, "_write_preview_html", render._write_preview_html)

    render._write_preview_html(workdir, theme="terracotta")

    final = (workdir / "article.html").read_text(encoding="utf-8")
    assert not CJK_PAIR_RE.search(final), (
        f"CJK-CJK space pattern survived _write_preview_html: {final[:300]!r}"
    )


def test_write_preview_html_keeps_clean_output_intact(tmp_path, monkeypatch):
    """If cli.py preview already produces clean HTML, _write_preview_html
    must not touch it (no extra xiaohu round-trip).
    """
    workdir = _make_workdir(tmp_path, "# 测试\n\n可得性启发。\n")
    clean_html = (
        "<!DOCTYPE html><html><head></head>"
        "<body><p>可得性启发。</p></body></html>"
    )
    written = {}

    def fake_run(cmd, **kwargs):
        out = cmd[cmd.index("-o") + 1]
        Path(out).write_text(clean_html, encoding="utf-8")
        written["count"] = written.get("count", 0) + 1
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    render._write_preview_html(workdir, theme="terracotta")

    assert written.get("count", 0) == 1, "should not re-render when output is already clean"


def test_insert_images_adds_cover_and_four_inline_images():
    md = """# 标题

> **分类**：心理学

## 摘要

摘要。

## § 1 起源

正文。

## § 2 机制

正文。

## § 3 证据

正文。

## § 4 应用

正文。
"""
    rels = [f"images/inline-{i}.jpg" for i in range(1, 5)]
    result = render._insert_images(md, "images/cover.jpg", rels)
    assert result.count("![") == 5
    assert result.count("images/cover.jpg") == 1
    for rel in rels:
        assert result.count(rel) == 1


def make_article_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "article.md").write_text(
        """# 标题

## 摘要

摘要正文。

## § 1 起源

第一节正文。

## § 2 机制

第二节正文。

## § 3 证据

第三节正文。

## § 4 应用

第四节正文。
""",
        encoding="utf-8",
    )
    return workdir


def raising_image_call(*args, **kwargs):
    raise RuntimeError("quota")


def test_web_image_failure_raises_without_placeholder(tmp_path, monkeypatch):
    """A failed initial image must not fabricate a preview-ready image set."""
    workdir = make_article_workdir(tmp_path)
    monkeypatch.setattr(render, "generate_image_with_provider", raising_image_call)

    with pytest.raises(RuntimeError, match="quota"):
        render.generate_images_in_workdir(
            workdir, TOPIC, render.default_image_rels(), IMAGE_SETTINGS
        )

    assert not (workdir / "image-status.json").exists()
    assert list((workdir / "images").iterdir()) == []


def test_generate_images_accepts_every_successful_provider_result(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    calls = []

    def fake_generate(prompt, output, provider_settings, size):
        calls.append((prompt, Path(output).name, size))
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image_with_provider", fake_generate)
    mode = render.generate_images_in_workdir(
        workdir, TOPIC, render.default_image_rels(), IMAGE_SETTINGS
    )

    assert mode == "real"
    assert len(calls) == 5
    states = json.loads((workdir / "image-status.json").read_text())
    assert set(states.values()) == {"real"}
    assert not (workdir / "image-diagnostics.json").exists()


ARTICLE_GROUNDING_MD = """# 一个含糊标题

> **分类**：心理学

![封面](images/cover.jpg)
## 摘要

青年在职业与城市之间反复迁移，通过探索逐渐建立身份认同。

![配图](images/inline-1.jpg)
## § 1 起源

报纸专栏作者观察到青年频繁迁徙、更换职业与亲密关系，由此提出新的成年过渡隐喻。

![配图](images/inline-2.jpg)
## § 2 发展演变

城市中产青年拥有主动探索空间，短期合同青年却被迫在家庭和临时工作之间循环。

![配图](images/inline-3.jpg)
## § 3 影响与应用

心理咨询师与青年面对面梳理职业选择背后的价值冲突，帮助探索行为去病理化。

![配图](images/inline-4.jpg)
## § 4 反直觉点

经济支持决定探索是自由还是被迫，同样的漂泊对不同青年意味着完全不同的机会。
"""


def test_generate_images_ground_each_prompt_in_matching_article_section(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "article.md").write_text(ARTICLE_GROUNDING_MD, encoding="utf-8")
    calls = []

    def fake_generate(prompt, output, provider_settings, size):
        calls.append(prompt)
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image_with_provider", fake_generate)
    topic = {"id": "custom-empty", "title": "一个含糊标题", "category": "心理学", "key_points": []}

    render.generate_images_in_workdir(
        workdir, topic, render.default_image_rels(), IMAGE_SETTINGS
    )

    expected_facts = [
        "青年在职业与城市之间反复迁移",
        "报纸专栏作者观察到青年频繁迁徙",
        "城市中产青年拥有主动探索空间",
        "心理咨询师与青年面对面梳理职业选择",
        "经济支持决定探索是自由还是被迫",
    ]
    assert len(calls) == 5
    for prompt, fact in zip(calls, expected_facts):
        assert fact in prompt
        assert "只使用内容依据中明确出现的实体、动作和环境" in prompt
    assert "“一个含糊标题”" in calls[0]
    assert all("一个含糊标题" not in prompt for prompt in calls[1:])
    expected_headings = ["起源", "发展演变", "影响与应用", "反直觉点"]
    for prompt, heading in zip(calls[1:], expected_headings):
        assert f"章节：{heading}" in prompt
        assert f"“{heading}”" in prompt


def test_generate_images_records_the_actual_prompts(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    (workdir / "article.md").write_text(ARTICLE_GROUNDING_MD, encoding="utf-8")
    generated = {}

    def fake_generate(prompt, output, provider_settings, size):
        generated[Path(output).stem] = prompt
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image_with_provider", fake_generate)
    topic = {"id": "custom-empty", "title": "一个含糊标题", "category": "心理学", "key_points": []}

    render.generate_images_in_workdir(
        workdir, topic, render.default_image_rels(), IMAGE_SETTINGS
    )

    saved = json.loads((workdir / "image-prompts.json").read_text(encoding="utf-8"))
    assert saved == generated


TOPIC = {
    "id": "kb-001",
    "title": "幸存者偏差",
    "category": "认知偏差",
    "key_points": ["返航轰炸机的弹孔分布", "沉默的证据", "选择效应", "现代商业误用"],
}

def _all_prompts(topic):
    return [render._cover_prompt(topic), *render._inline_prompts(topic)]


def test_prompts_share_one_editorial_visual_system():
    for prompt in _all_prompts(TOPIC):
        assert "当代科普编辑插画" in prompt
        assert "全篇统一视觉系统" in prompt
        assert "低饱和海军蓝、赭石与暖象牙色" in prompt
        assert "最多两个人" in prompt
        assert "最多四个关键物件" in prompt


def test_cover_uses_the_exact_short_topic_name_as_optional_visible_text():
    topic = {
        **TOPIC,
        "title": "损失厌恶：人类决策中收益与损失的不对称评价",
    }
    prompt = render._cover_prompt(topic)
    assert "单幅概念封面" in prompt
    assert "可见文字" in prompt
    assert "“损失厌恶”" in prompt
    assert topic["title"] not in prompt
    assert "不得添加其他文字、数字、Logo 或水印" in prompt


def test_cover_uses_visual_hierarchy_without_percentage_layout_rules():
    prompt = render._cover_prompt(TOPIC)
    assert "主体、关键动作和对比关系一眼可辨" in prompt
    assert "百分之八十" not in prompt
    assert "百分之八" not in prompt
    assert "四分之一" not in prompt


def test_inline_prompts_follow_actual_sections_instead_of_fixed_scene_roles():
    briefs = [
        ("参照点如何改变判断", "顾客同时看到涨价商品和降价商品，重新衡量得失。"),
        ("硬币实验", "参与者先拿到一枚硬币，再决定是否交换。"),
        ("消费现场", "旅客在退票窗口比较手续费与继续出行的成本。"),
        ("适用边界", "经验丰富的交易员仍会检查概率与最终财富。"),
    ]
    prompts = render._inline_prompts(TOPIC, briefs)
    for prompt, (heading, fact) in zip(prompts, briefs):
        assert f"章节：{heading}" in prompt
        assert fact in prompt
        assert f"“{heading}”" in prompt
    joined = "".join(prompts)
    assert "起源瞬间" not in joined
    assert "发展变化瞬间" not in joined
    assert "影响或应用瞬间" not in joined
    assert "反直觉判断" not in joined


def test_article_briefs_keep_full_section_heading_for_visual_context():
    markdown = """# 标题

## 摘要

摘要内容。

## § 1 参照点如何改变收益与损失的判断

顾客把同样金额的损失看得比收益更重。
"""
    _, sections = render._article_visual_briefs(markdown)
    assert sections == [
        ("参照点如何改变收益与损失的判断", "顾客把同样金额的损失看得比收益更重。")
    ]


def test_long_section_heading_uses_short_topic_label_without_truncating_words():
    topic = {
        **TOPIC,
        "title": "损失厌恶：人类决策中收益与损失的不对称评价",
    }
    prompt = render._inline_prompts(
        topic,
        [("参照点如何改变收益与损失的判断", "顾客在退货柜台比较损失与收益。")],
    )[0]
    assert "章节：参照点如何改变收益与损失的判断" in prompt
    assert "可见文字：仅可使用原文短标签“损失厌恶”" in prompt
    assert "“参照点如何改变收益与损失”" not in prompt


def test_prompts_keep_topic_semantics_as_visual_context():
    for point, prompt in zip(TOPIC["key_points"], render._inline_prompts(TOPIC)):
        assert point in prompt


def test_prompts_allow_exact_source_labels_but_reject_invented_text():
    for prompt in _all_prompts(TOPIC):
        assert "可见文字" in prompt
        assert "文字必须逐字准确" in prompt
        assert "不得添加其他文字、数字、Logo 或水印" in prompt
        assert "zero typography" not in prompt


def test_behavioral_science_prompts_reject_generic_lab_decorations():
    for prompt in _all_prompts(TOPIC):
        assert "不得使用烧瓶、试管、分子结构、化学公式、显微镜或装饰性柱状图" in prompt


def test_non_behavioral_topics_get_a_generic_domain_relevance_rule():
    topic = {
        "title": "板块构造",
        "category": "地质学",
        "key_points": ["大陆漂移", "地幔对流", "地震证据", "板块边界"],
    }
    prompt = render._cover_prompt(topic)
    assert "器材和符号必须直接属于主题领域" in prompt
    assert "不得使用烧瓶、试管" not in prompt


def test_ensure_default_image_references_upgrades_legacy_article(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    legacy = """# 标题

> **分类**：心理学

![封面](images/cover.jpg)

## 摘要

摘要。

## § 1 起源

![配图](images/inline-1.jpg)

## § 2 机制

## § 3 证据

![配图](images/inline-2.jpg)

## § 4 应用
"""
    (workdir / "article.md").write_text(legacy, encoding="utf-8")
    render.ensure_default_image_references(workdir)
    upgraded = (workdir / "article.md").read_text(encoding="utf-8")
    assert upgraded.count("![") == 5
    for rel in render.default_image_rels():
        assert upgraded.count(rel) == 1
