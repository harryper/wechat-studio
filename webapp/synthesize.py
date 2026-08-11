"""Generate a markdown skeleton from a corpus topic for preview rendering.

This is a STRUCTURAL MOCK — the synthesized article uses the topic's metadata
(origin, key_points, caution) but the body prose is not real article content.
The purpose is to let the user see the visual effect of a theme on a topic
before they commit to generating the actual article via the normal pipeline.
"""

from typing import Any, Dict


def synthesize_markdown(topic: Dict[str, Any]) -> str:
    """Build a markdown article skeleton from a topic dict.

    Output matches the shape of a finished article (H1 title, sections, list,
    optional warning) so that ``toolkit/cli.py preview`` and the theme CSS
    exercise the same DOM nodes they would for a real draft.
    """
    topic_id = topic.get("id") or topic.get("topic_id", "")
    title = topic.get("title", "")
    category = topic.get("category", "")
    origin = topic.get("origin", "（暂无）")
    key_points = topic.get("key_points", []) or []
    caution = topic.get("caution", "no")

    lines = [
        f"# {topic_id}：{title}",
        "",
        f"> **分类**：{category}　　**主题 ID**：`{topic_id}`",
        "",
        "## 摘要",
        "",
        f"本文将梳理「{title}」的核心要点。本文为逻辑梳理，非学术研究。",
        "",
        "## § 1 起源",
        "",
        origin,
        "",
        "## § 2 核心要点",
        "",
    ]
    for kp in key_points:
        lines.append(f"- {kp}")
    lines.extend(
        [
            "",
            "## § 3 影响与应用",
            "",
            f"在实际场景中，{title} 常被用于解释某种系统性偏差。",
            "",
            "## § 4 反直觉点",
            "",
            "常见的误解是把该现象归因为运气或个体差异，忽略了结构性原因。",
            "",
        ]
    )
    if caution == "yes":
        lines.extend(
            [
                "## ⚠️ 警示",
                "",
                "该主题在公共传播中存在大量简化版本，请以原始文献为准。",
                "",
            ]
        )
    return "\n".join(lines)
