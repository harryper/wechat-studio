#!/usr/bin/env python3
"""
CLI entry point for WeChat Studio.

Usage:
    python cli.py preview article.md --theme professional-clean
    python cli.py publish article.md --appid wx123 --secret abc123
    python cli.py themes
"""

import argparse
import sys
import webbrowser
from pathlib import Path

import yaml

from converter import WeChatConverter, preview_html
from xiaohu_formatter import format_article as xiaohu_format_article, list_xiaohu_themes
from theme import load_theme, list_themes
from wechat_api import get_access_token, upload_image, upload_thumb
from publisher import create_draft, create_image_post

# Config file search order
CONFIG_PATHS = [
    Path.cwd() / "config.yaml",
    Path(__file__).parent.parent / "config.yaml",  # skill root
    Path(__file__).parent / "config.yaml",          # toolkit dir
    Path.home() / ".config" / "wechat-studio" / "config.yaml",
]


import os, re

def _load_env_files() -> None:
    """Load local uncommitted env files so cron/subagents work without sourcing ~/.bashrc."""
    for env_path in [Path(__file__).parent.parent / ".env", Path.cwd() / ".env"]:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)

def _expand_env(value):
    """Recursively expand ${VAR} and $VAR patterns in config values."""
    if isinstance(value, str):
        # Support ${VAR} and ${VAR:-default} syntax
        pattern = r'\$\{([^}:]+)(?::-(.*?))?\}'
        def replacer(m):
            var, default = m.group(1), m.group(2)
            return os.environ.get(var, os.environ.get(var.upper(), default if default is not None else m.group(0)))
        return re.sub(pattern, replacer, value)
    elif isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value

def load_config() -> dict:
    """Load config from first found config.yaml with environment variable expansion."""
    _load_env_files()
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return _expand_env(cfg)
    return {}


DISCLAIMER = "\n\n---\n\n> **声明**：本文为逻辑梳理，非学术研究。引用细节可能存在简化。\n"


def inject_disclaimer(markdown: str) -> str:
    """Append academic disclaimer. Idempotent."""
    if DISCLAIMER.strip() in markdown:
        return markdown
    return markdown.rstrip() + DISCLAIMER


def cmd_preview(args):
    """Generate HTML preview and open in browser.
    
    Routes to xiaohu formatter for xiaohu themes (full container syntax),
    or to legacy wechat-studio converter for other themes.
    """
    theme_name = args.theme
    xiaohu_themes = list_xiaohu_themes()
    use_xiaohu = theme_name in xiaohu_themes

    md_text = _sanitize_article_markdown(Path(args.input).read_text(encoding='utf-8'))
    input_path = Path(args.input)
    output = args.output or str(input_path.with_suffix(".html"))

    if use_xiaohu:
        # Use xiaohu formatter for full container syntax support
        print(f"Using xiaohu formatter, theme: {theme_name}")
        html = xiaohu_format_article(md_text, theme=theme_name)
        title, digest = _extract_title_and_digest(md_text)
        images = _extract_images_from_md(md_text)
        # Wrap xiaohu output in basic HTML shell (no CSS class system)
        full_html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>body{{margin:0;padding:0;background:#f5f5f5}}</style>
</head>
<body>
{html}
</body>
</html>'''
    else:
        # Use legacy wechat-studio converter
        theme = load_theme(theme_name)
        converter = WeChatConverter(theme=theme)
        result = converter.convert(md_text)
        html = result.html
        title = result.title
        digest = result.digest
        images = result.images
        full_html = preview_html(html, theme)

    Path(output).write_text(full_html, encoding='utf-8')

    print(f"Title: {title}")
    print(f"Digest: {digest[:60]}...")
    print(f"Images: {len(images)}")
    print(f"Output: {output}")

    if not args.no_open:
        webbrowser.open(f"file://{Path(output).absolute()}")
        print("Opened in browser.")



def cmd_publish(args):
    """Convert, upload images, and create WeChat draft."""
    cfg = load_config()
    wechat_cfg = cfg.get("wechat", {})

    # Resolve from CLI args → config.yaml fallback
    appid = args.appid or wechat_cfg.get("appid")
    secret = args.secret or wechat_cfg.get("secret")
    theme_name = args.theme or cfg.get("theme", "professional-clean")
    author = args.author or wechat_cfg.get("author")

    if not appid or not secret:
        print("Error: --appid and --secret required (or set in config.yaml)", file=sys.stderr)
        sys.exit(1)

    md_text = Path(args.input).read_text(encoding='utf-8')
    xiaohu_themes = list_xiaohu_themes()
    use_xiaohu = theme_name in xiaohu_themes

    if use_xiaohu:
        # Use xiaohu formatter (full container syntax support)
        print(f"Using xiaohu formatter, theme: {theme_name}")
        html = xiaohu_format_article(md_text, theme=theme_name)
        title, digest = _extract_title_and_digest(md_text)
        images = _extract_images_from_md(md_text)
        print(f"Title: {title}")
        print(f"Digest: {digest[:60]}...")
        print(f"Images found: {len(images)}")
    else:
        # Use legacy wechat-studio converter
        theme = load_theme(theme_name)
        converter = WeChatConverter(theme=theme)
        result = converter.convert_file(args.input)
        html = result.html
        title = result.title
        digest = result.digest
        images = result.images
        print(f"Title: {result.title}")
        print(f"Digest: {result.digest[:60]}...")
        print(f"Images found: {len(images)}")

    # Get access token
    token = get_access_token(appid, secret)
    print("Access token obtained.")

    # Upload images referenced in article and replace src
    md_dir = Path(args.input).resolve().parent

    for img_src in images:
        if img_src.startswith(("http://", "https://")):
            print(f"Skipping remote image: {img_src}")
            continue

        img_path = Path(img_src)
        if not img_path.is_absolute():
            if not img_path.exists():
                img_path = md_dir / img_src

        if img_path.exists():
            print(f"Uploading image: {img_src}")
            wechat_url = upload_image(token, str(img_path))
            html = html.replace(img_src, wechat_url)
            print(f"  -> {wechat_url}")
        else:
            print(f"Warning: image not found: {img_src} (searched {md_dir})")

    # Upload cover image if provided
    thumb_media_id = None
    if args.cover:
        print(f"Uploading cover: {args.cover}")
        thumb_media_id = upload_thumb(token, args.cover)
        print(f"  -> media_id: {thumb_media_id}")

    # Create draft
    title = args.title or title or Path(args.input).stem
    digest_arg = args.digest or digest
    draft = create_draft(
        access_token=token,
        title=title,
        html=html,
        digest=digest_arg,
        thumb_media_id=thumb_media_id,
        author=author,
    )

    print(f"\nDraft created! media_id: {draft.media_id}")


def _extract_title_and_digest(md_text: str):
    """Extract title (H1) and digest from markdown text."""
    import re
    lines = md_text.strip().split('\n')
    title = ''
    for line in lines:
        m = re.match(r'^#\s+(.+)', line)
        if m:
            title = m.group(1).strip()
            break
    digest_lines = []
    in_code = False
    for line in lines:
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('>') and not line.startswith('!'):
            digest_lines.append(line)
            if len(' '.join(digest_lines)) > 120:
                break
    digest = ' '.join(digest_lines)[:120]
    return title, digest


def _sanitize_article_markdown(md_text: str) -> str:
    """Keep only the publishable article body if draft notes wrapped the final copy."""
    lines = md_text.splitlines()
    final_heading_idx = None
    final_heading_re = re.compile(r"^#\s*【?(?:终稿|最终稿|定稿|正文)】?\s*$")
    for idx, line in enumerate(lines):
        if final_heading_re.match(line.strip()):
            final_heading_idx = idx
            break

    if final_heading_idx is not None:
        lines = lines[final_heading_idx + 1 :]
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and lines[0].startswith("## "):
            lines[0] = "# " + lines[0][3:].strip()

    return "\n".join(lines).strip() + "\n"


def _extract_images_from_md(md_text: str) -> list[str]:
    """Extract image paths from markdown text."""
    import re
    return re.findall(r'!\[.*?\]\((.*?)\)', md_text)


def cmd_publish(args):
    """Convert, upload images, and create WeChat draft."""
    cfg = load_config()
    wechat_cfg = cfg.get("wechat", {})

    # Resolve from CLI args → config.yaml fallback
    appid = args.appid or wechat_cfg.get("appid")
    secret = args.secret or wechat_cfg.get("secret")
    theme_name = args.theme or cfg.get("theme", "professional-clean")
    author = args.author or wechat_cfg.get("author")

    if not appid or not secret:
        print("Error: --appid and --secret required (or set in config.yaml)", file=sys.stderr)
        sys.exit(1)

    md_text = _sanitize_article_markdown(Path(args.input).read_text(encoding='utf-8'))
    md_text = inject_disclaimer(md_text)
    xiaohu_themes = list_xiaohu_themes()
    use_xiaohu = theme_name in xiaohu_themes

    if use_xiaohu:
        # Use xiaohu formatter (full container syntax support)
        print(f"Using xiaohu formatter with theme: {theme_name}")
        html = xiaohu_format_article(md_text, theme=theme_name)
        title, digest = _extract_title_and_digest(md_text)
        images = _extract_images_from_md(md_text)
        print(f"Title: {title}")
        print(f"Digest: {digest[:60]}...")
        print(f"Images found: {len(images)}")
    else:
        # Use legacy wechat-studio converter
        theme = load_theme(theme_name)
        converter = WeChatConverter(theme=theme)
        result = converter.convert(md_text)
        html = result.html
        title = result.title
        digest = result.digest
        images = result.images
        print(f"Title: {result.title}")
        print(f"Digest: {result.digest[:60]}...")
        print(f"Images found: {len(images)}")

    # Get access token
    token = get_access_token(appid, secret)
    print("Access token obtained.")

    # Upload images referenced in article and replace src
    # Resolve relative paths against the markdown file's directory
    md_dir = Path(args.input).resolve().parent

    for img_src in images:
        if img_src.startswith(("http://", "https://")):
            print(f"Skipping remote image: {img_src}")
            continue

        # Try: absolute → relative to CWD → relative to markdown file
        img_path = Path(img_src)
        if not img_path.is_absolute():
            if not img_path.exists():
                img_path = md_dir / img_src

        if img_path.exists():
            print(f"Uploading image: {img_src}")
            wechat_url = upload_image(token, str(img_path))
            html = html.replace(img_src, wechat_url)
            print(f"  -> {wechat_url}")
        else:
            print(f"Warning: image not found: {img_src} (searched {md_dir})")

    # Upload cover image if provided
    thumb_media_id = None
    if args.cover:
        print(f"Uploading cover: {args.cover}")
        thumb_media_id = upload_thumb(token, args.cover)
        print(f"  -> media_id: {thumb_media_id}")

    # Create draft
    title = args.title or title or Path(args.input).stem
    digest = args.digest or digest
    draft = create_draft(
        access_token=token,
        title=title,
        html=html,
        digest=digest,
        thumb_media_id=thumb_media_id,
        author=author,
    )

    print(f"\nDraft created! media_id: {draft.media_id}")


def cmd_themes(args):
    """List available themes (both wechat-studio native + xiaohu)."""
    names = list_themes()
    xiaohu = set(list_xiaohu_themes())
    for name in names:
        theme = load_theme(name)
        tag = " [xiaohu]" if name in xiaohu else ""
        print(f"  {name:24s} {theme.description}{tag}")


def cmd_image_post(args):
    """Create a WeChat image post (小绿书) from image files."""
    cfg = load_config()
    wechat_cfg = cfg.get("wechat", {})

    appid = args.appid or wechat_cfg.get("appid")
    secret = args.secret or wechat_cfg.get("secret")

    if not appid or not secret:
        print("Error: --appid and --secret required (or set in config.yaml)", file=sys.stderr)
        sys.exit(1)

    images = args.images
    if not images:
        print("Error: at least 1 image required", file=sys.stderr)
        sys.exit(1)
    if len(images) > 20:
        print(f"Error: max 20 images, got {len(images)}", file=sys.stderr)
        sys.exit(1)

    token = get_access_token(appid, secret)
    print(f"Uploading {len(images)} images as permanent materials...")

    media_ids = []
    for img_path in images:
        p = Path(img_path)
        if not p.exists():
            print(f"Error: image not found: {img_path}", file=sys.stderr)
            sys.exit(1)
        print(f"  Uploading: {p.name}")
        mid = upload_thumb(token, str(p))
        media_ids.append(mid)
        print(f"    -> {mid}")

    title = args.title
    if len(title) > 32:
        print(f"Warning: title truncated to 32 chars (was {len(title)})")
        title = title[:32]

    content = args.content or ""

    result = create_image_post(
        access_token=token,
        title=title,
        image_media_ids=media_ids,
        content=content,
        open_comment=True,
    )

    print(f"\nImage post draft created!")
    print(f"  media_id: {result.media_id}")
    print(f"  images: {result.image_count}")
    print(f"  title: {title}")
    print(f"  请到公众号后台草稿箱检查并发布")


def cmd_gallery(args):
    """Render all themes side by side in a browser gallery."""
    from concurrent.futures import ThreadPoolExecutor

    # Use provided markdown or a built-in sample
    if args.input:
        md_text = Path(args.input).read_text(encoding="utf-8")
    else:
        md_text = _gallery_sample_markdown()

    names = list_themes()
    results = {}

    def render_theme(name):
        theme = load_theme(name)
        converter = WeChatConverter(theme=theme)
        result = converter.convert(md_text)
        return name, theme.description, result.html

    # Parallel rendering
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, desc, html in pool.map(lambda n: render_theme(n), names):
            results[name] = (desc, html)

    # Build gallery HTML
    gallery_html = _build_gallery_html(results, names)
    output = args.output or "/tmp/wechat-studio-gallery.html"
    Path(output).write_text(gallery_html, encoding="utf-8")
    print(f"Gallery: {output} ({len(names)} themes)")

    if not args.no_open:
        webbrowser.open(f"file://{Path(output).absolute()}")


def cmd_learn_theme(args):
    """Learn a theme from a WeChat article URL."""
    import subprocess
    script = Path(__file__).parent.parent / "scripts" / "learn_theme.py"
    cmd = [sys.executable, str(script), args.url, "--name", args.name]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def _gallery_sample_markdown():
    return """# 示例文章标题

## 第一部分

这是一段正常的文章内容，用来展示不同主题的排版效果。WeChat Studio 支持多种排版主题，每种都有独特的视觉风格。

说实话，选主题这件事——看截图永远不如看实际渲染效果。

## 关键数据

| 指标 | 数值 | 变化 |
|------|------|------|
| 阅读量 | 12,580 | +23% |
| 分享率 | 4.7% | +0.8% |
| 完读率 | 68% | -2% |

## 代码示例

```python
def hello():
    print("Hello, WeChat Studio!")
```

> 好的排版不是让读者注意到设计，而是让读者忘记设计，只记住内容。

## 列表展示

- 第一个要点：简洁是设计的灵魂
- 第二个要点：一致性比创意更重要
- 第三个要点：移动端体验优先

**加粗文本**和*斜体文本*的样式也需要关注。

最后这段用来展示文章结尾的留白和间距效果。一篇好文章的结尾，应该像一首好歌的最后一个音符——恰到好处地收束。
"""


def _join_newline(items):
    """Join items with comma + newline (workaround for f-string limitation)."""
    return ",\n".join(items)


def _build_gallery_html(results, names):
    cards = []
    for name in names:
        desc, html = results[name]
        # Escape for embedding in JS
        escaped_html = html.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')
        cards.append(f"""
        <div class="theme-card" onclick="selectTheme('{name}')">
          <div class="theme-name">{name}</div>
          <div class="theme-desc">{desc}</div>
          <div class="phone-frame">
            <div class="phone-content" id="preview-{name}">{html}</div>
          </div>
          <button class="copy-btn" onclick="event.stopPropagation(); copyHTML('{name}')">复制 HTML</button>
        </div>""")

    # Store HTML data for copy
    data_entries = []
    for name in names:
        desc, html = results[name]
        safe = html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
        data_entries.append(f"  '{name}': '{safe}'")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WeChat Studio 主题画廊</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f0f0f; color: #fff; }}
.header {{ text-align: center; padding: 40px 20px 20px; }}
.header h1 {{ font-size: 28px; font-weight: 700; }}
.header p {{ color: #888; margin-top: 8px; font-size: 15px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 24px; padding: 24px; max-width: 1440px; margin: 0 auto; }}
.theme-card {{ background: #1a1a1a; border-radius: 12px; padding: 16px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }}
.theme-card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
.theme-name {{ font-size: 16px; font-weight: 700; margin-bottom: 4px; }}
.theme-desc {{ font-size: 13px; color: #888; margin-bottom: 12px; }}
.phone-frame {{ background: #fff; border-radius: 8px; overflow: hidden; max-height: 480px; overflow-y: auto; }}
.phone-content {{ padding: 16px; font-size: 14px; transform: scale(0.85); transform-origin: top left; width: 118%; }}
.copy-btn {{ margin-top: 12px; width: 100%; padding: 8px; background: #333; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
.copy-btn:hover {{ background: #555; }}
.toast {{ position: fixed; bottom: 40px; left: 50%; transform: translateX(-50%); background: #333; color: #fff; padding: 10px 24px; border-radius: 8px; font-size: 14px; display: none; z-index: 999; }}
</style>
</head>
<body>
<div class="header">
  <h1>WeChat Studio 主题画廊</h1>
  <p>{len(names)} 个主题 · 点击卡片查看大图 · 点击「复制 HTML」直接粘贴到公众号编辑器</p>
</div>
<div class="grid">
{''.join(cards)}
</div>
<div class="toast" id="toast">已复制到剪贴板</div>
<script>
const themeData = {{
{_join_newline(data_entries)}
}};
function copyHTML(name) {{
  const html = themeData[name];
  if (html) {{
    navigator.clipboard.writeText(html).then(() => {{
      const t = document.getElementById('toast');
      t.style.display = 'block';
      setTimeout(() => t.style.display = 'none', 1500);
    }});
  }}
}}
function selectTheme(name) {{
  localStorage.setItem('wechat-studio-theme', name);
  // Scroll to card for visual feedback
  const el = document.getElementById('preview-' + name);
  if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
}}
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        prog="wechat-studio",
        description="Markdown to WeChat HTML converter and publisher",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # preview
    p_preview = sub.add_parser("preview", help="Generate HTML and open in browser")
    p_preview.add_argument("input", help="Markdown file path")
    p_preview.add_argument("-t", "--theme", default="professional-clean", help="Theme name")
    p_preview.add_argument("-o", "--output", help="Output HTML file path")
    p_preview.add_argument("--no-open", action="store_true", help="Don't open browser")

    # publish
    p_publish = sub.add_parser("publish", help="Convert and publish as WeChat draft")
    p_publish.add_argument("input", help="Markdown file path")
    p_publish.add_argument("-t", "--theme", default=None, help="Theme name")
    p_publish.add_argument("--appid", default=None, help="WeChat AppID (or set in config.yaml)")
    p_publish.add_argument("--secret", default=None, help="WeChat AppSecret (or set in config.yaml)")
    p_publish.add_argument("--cover", help="Cover image file path")
    p_publish.add_argument("--title", help="Override article title")
    p_publish.add_argument("--author", default=None, help="Article author")
    p_publish.add_argument("--digest", default=None, help="Override article digest (≤120 UTF-8 bytes)")

    # themes
    sub.add_parser("themes", help="List available themes")

    # image-post (小绿书)
    p_imgpost = sub.add_parser("image-post", help="Create WeChat image post (小绿书)")
    p_imgpost.add_argument("images", nargs="+", help="Image file paths (1-20, first = cover)")
    p_imgpost.add_argument("-t", "--title", required=True, help="Post title (max 32 chars)")
    p_imgpost.add_argument("-c", "--content", default="", help="Plain text description (max ~1000 chars)")
    p_imgpost.add_argument("--appid", default=None, help="WeChat AppID")
    p_imgpost.add_argument("--secret", default=None, help="WeChat AppSecret")

    # gallery
    p_gallery = sub.add_parser("gallery", help="Open theme gallery in browser")
    p_gallery.add_argument("input", nargs="?", default=None, help="Markdown file (optional, uses sample if omitted)")
    p_gallery.add_argument("-o", "--output", help="Output HTML file path")
    p_gallery.add_argument("--no-open", action="store_true", help="Don't open browser")

    # learn-theme
    p_learn = sub.add_parser("learn-theme", help="Learn formatting theme from a WeChat article URL")
    p_learn.add_argument("url", help="WeChat article URL")
    p_learn.add_argument("--name", required=True, help="Theme name")

    args = parser.parse_args()

    try:
        if args.command == "preview":
            cmd_preview(args)
        elif args.command == "publish":
            cmd_publish(args)
        elif args.command == "themes":
            cmd_themes(args)
        elif args.command == "image-post":
            cmd_image_post(args)
        elif args.command == "gallery":
            cmd_gallery(args)
        elif args.command == "learn-theme":
            cmd_learn_theme(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
