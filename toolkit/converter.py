"""
Markdown → WeChat HTML converter.

Delegates to xiaohu-wechat-format for full container syntax support
(callout, gallery, timeline, dialogue, darkmode injection).
Falls back to a minimal converter for other themes.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConvertResult:
    """Result of a Markdown → WeChat HTML conversion."""

    html: str  # WeChat-compatible inline-style HTML (body only, no wrapper)
    title: str  # Extracted H1 title (or empty string)
    digest: str  # Auto-generated summary (first 120 chars plain text)
    images: list[str] = field(default_factory=list)  # Image paths referenced


class WeChatConverter:
    """
    Convert Markdown to WeChat-compatible inline-style HTML.

    Routes to xiaohu engine for themes xiaohu knows (full container support),
    otherwise uses the basic converter.
    """

    def __init__(self, theme=None, theme_name: str = "professional-clean"):
        self._theme_name = theme_name

    def convert(self, markdown_text: str) -> ConvertResult:
        """Convert Markdown text → WeChat HTML."""
        from xiaohu_formatter import format_article, list_xiaohu_themes

        xiaohu_themes = list_xiaohu_themes()
        use_xiaohu = self._theme_name in xiaohu_themes

        title = _extract_title(markdown_text)
        body_md = _strip_title(markdown_text)

        if use_xiaohu:
            html = format_article(body_md, theme=self._theme_name)
        else:
            html = self._basic_convert(body_md)

        images = _extract_image_paths(markdown_text)
        digest = _generate_digest(html)

        return ConvertResult(html=html, title=title, digest=digest, images=images)

    def convert_file(self, input_path: str) -> ConvertResult:
        """Convert a Markdown file."""
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        text = path.read_text(encoding="utf-8")
        return self.convert(text)

    def _basic_convert(self, markdown_text: str) -> str:
        """Minimal converter for non-xiaohu themes."""
        import markdown
        from bs4 import BeautifulSoup

        text = _fix_cjk_spacing(markdown_text)
        html = markdown.markdown(
            text,
            extensions=["tables", "fenced_code", "nl2br"],
        )
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all("blockquote"):
            tag["style"] = (
                "border-left:4px solid #c8c8c8;"
                "background:#f6f6f6;"
                "padding:12px 16px;"
                "margin:16px 0;"
                "border-radius:0 6px 6px 0"
            )
        for code in soup.find_all("code"):
            code["style"] = "background:#f0f0f0;padding:2px 6px;border-radius:3px;font-size:90%"
        for pre in soup.find_all("pre"):
            pre["style"] = "background:#fafafa;padding:16px;border-radius:8px;overflow-x:auto"
        for table in soup.find_all("table"):
            table["style"] = "width:100%;border-collapse:collapse;margin:16px 0"
            for td in table.find_all(["th", "td"]):
                td["style"] = "padding:8px 12px;border:1px solid #e5e5e5"
        for hr in soup.find_all("hr"):
            hr["style"] = "border:none;border-top:1px dashed #e5e5e5;margin:24px 0"

        return str(soup)


# ── Helpers ──────────────────────────────────────────────────────────────

def _extract_title(md: str) -> str:
    """Extract first H1 from markdown."""
    for line in md.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _strip_title(md: str) -> str:
    """Remove the first H1 title line (WeChat uses its own title field)."""
    lines, skipped = [], False
    for line in md.split("\n"):
        if not skipped and line.strip().startswith("# "):
            skipped = True
            continue
        lines.append(line)
    return "\n".join(lines)


def _extract_image_paths(markdown_text: str) -> list[str]:
    """Extract all ![alt](path) image references from markdown."""
    return re.findall(r"!\[.*?\]\((.*?)\)", markdown_text)


def _generate_digest(html: str, max_bytes: int = 120) -> str:
    """Generate plain-text digest fitting WeChat's byte limit."""
    from bs4 import BeautifulSoup

    text = re.sub(
        r"\s+", " ",
        BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    )
    ellipsis = "..."
    target = max_bytes - len(ellipsis.encode("utf-8"))
    result = ""
    for char in text:
        cb = len(char.encode("utf-8"))
        if len(result.encode("utf-8")) + cb > target:
            break
        result += char
    return result + ellipsis


def _fix_cjk_spacing(text: str) -> str:
    """Add space between CJK and non-CJK characters."""
    cjk = "\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u309f\u30a0-\u30ff"
    text = re.sub(f"([{cjk}])([{cjk}])", r"\1 \2", text)
    text = re.sub(f"([{cjk}])([a-zA-Z])", r"\1 \2", text)
    text = re.sub(f"([a-zA-Z])([{cjk}])", r"\1 \2", text)
    return text


def preview_html(body_html: str, theme) -> str:
    """
    Wrap body content in a full HTML document for local browser preview.
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Preview</title>
    <style>
        body {{
            font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
            max-width: 720px;
            margin: 0 auto;
            padding: 16px;
            background: #f5f5f5;
        }}
    </style>
</head>
<body>
{body_html}
</body>
</html>"""
