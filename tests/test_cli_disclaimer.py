import sys
from pathlib import Path

# toolkit/cli.py uses bare imports like `from converter import ...` which
# only resolve when the toolkit directory itself is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "toolkit"))

import pytest
from toolkit.cli import inject_disclaimer, DISCLAIMER


def test_inject_disclaimer_appends():
    md = "# 幸存者偏差\n\n正文内容"
    out = inject_disclaimer(md)
    assert "本文为逻辑梳理" in out
    assert "非学术研究" in out


def test_inject_disclaimer_idempotent():
    md = "# 幸存者偏差\n\n正文\n\n" + DISCLAIMER.strip()
    out = inject_disclaimer(md)
    assert out.count("本文为逻辑梳理") == 1


def test_inject_disclaimer_preserves_frontmatter():
    md = "---\ntitle: foo\n---\n\n# 标题\n\n正文"
    out = inject_disclaimer(md)
    # Disclaimer goes after content, before frontmatter stays
    assert out.startswith("---\n")
    assert "本文为逻辑梳理" in out