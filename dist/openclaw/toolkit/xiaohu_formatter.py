#!/usr/bin/env python3
"""
Bridge: use xiaohu-wechat-format's format.py as the HTML formatter.
Wewrite keeps: image gen, upload, draft publishing.
xiaohu keeps: markdown→WeChat HTML with full container support.

Usage:
    from xiaohu_formatter import format_article
    html = format_article(markdown_text, theme_name="terracotta")
"""

import subprocess
import tempfile
import uuid
from pathlib import Path


XIAOHU_FORMAT_PY = Path(__file__).parent.parent.parent / "xiaohu-wechat-format" / "scripts" / "format.py"


def format_article(markdown_text: str, theme: str = "terracotta") -> str:
    """
    Convert markdown text to WeChat-compatible inline-style HTML
    using xiaohu-wechat-format's format.py engine.

    Args:
        markdown_text: Full article markdown
        theme: xiaohu theme name (e.g. "terracotta", "mint-fresh", "magazine")

    Returns:
        Inline-style HTML (body content, no <html>/<head> wrapper)
        suitable for upload + draft creation.
    """
    # Write markdown to a temp file (xiaohu format.py reads from file)
    tmp_md = Path(tempfile.gettempdir()) / f"wechat_studio_{uuid.uuid4().hex[:8]}.md"
    tmp_md.write_text(markdown_text, encoding="utf-8")

    # Output to a temp dir
    tmp_out = Path(tempfile.gettempdir()) / f"wechat_studio_out_{uuid.uuid4().hex[:8]}"
    tmp_out.mkdir(exist_ok=True)

    try:
        result = subprocess.run(
            [
                "python3",
                str(XIAOHU_FORMAT_PY),
                "--input", str(tmp_md),
                "--theme", theme,
                "--format", "wechat",
                "--no-open",
                "--output", str(tmp_out),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # xiaohu outputs article.html in the output dir
        article_html = tmp_out / tmp_md.stem / "article.html"
        if not article_html.exists():
            # Try alternate path structure
            candidates = list(tmp_out.rglob("article.html"))
            if candidates:
                article_html = candidates[0]

        if article_html and article_html.exists():
            return article_html.read_text(encoding="utf-8")
        else:
            raise RuntimeError(
                f"xiaohu format.py failed to produce article.html.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
    finally:
        # Cleanup temp files
        tmp_md.unlink(missing_ok=True)
        # Keep tmp_out for debugging if needed


def list_xiaohu_themes() -> list[str]:
    """Return list of available xiaohu theme names."""
    themes_dir = Path(__file__).parent.parent.parent / "xiaohu-wechat-format" / "themes"
    return sorted([p.stem for p in themes_dir.glob("*.json")])


if __name__ == "__main__":
    # Quick test
    test_md = """# 测试标题

## 01 · 第一个小节

这是一段正文。

> [!important] 重点结论
> 这是重点内容。

## 02 · 第二小节

:::gallery
![图1](img1.jpg)
![图2](img2.jpg)
:::
"""
    html = format_article(test_md, "terracotta")
    print(f"Generated HTML: {len(html)} chars")
    print(html[:500])
