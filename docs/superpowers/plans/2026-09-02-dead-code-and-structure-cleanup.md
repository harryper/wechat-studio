# Dead Code and Project Structure Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove demonstrably unused code and dependencies, keep compatibility-sensitive entry points, and make the checked-in OpenClaw distribution contain runtime assets only.

**Architecture:** Preserve all documented CLI and runtime flows. Enforce the source/distribution boundary in `scripts/build_openclaw.py`, remove unreachable legacy implementations from source, then regenerate `dist/openclaw` from the cleaned source tree.

**Tech Stack:** Python 3.11, Pytest, YAML, Flask, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-02-dead-code-and-structure-cleanup-design.md`

## Global Constraints

- Do not change article generation, image generation, rendering, Web API, D1, or publishing behavior.
- Preserve every command documented in `README.md` or `SKILL.md`.
- Preserve `scripts/migrate_history.py`, `scripts/backfill_signals.py`, `_build_provider`, `mark_interrupted_jobs`, and `upsert_corpus`.
- Do not modify `.env`, credentials, client data, `output/`, `workspace/`, or `webapp/_data/`.
- Keep `dist/openclaw` checked in and generated exclusively by `scripts/build_openclaw.py`.

---

### Task 1: Enforce the OpenClaw Distribution Boundary

**Files:**
- Create: `tests/test_build_openclaw.py`
- Modify: `scripts/build_openclaw.py`
- Regenerate later: `dist/openclaw/`

**Interfaces:**
- Consumes: `scripts.build_openclaw.build(output_dir: pathlib.Path) -> None`.
- Produces: a distribution containing runtime references, scripts, toolkit files, personas, and configuration templates while excluding development and builder-only files.

- [ ] **Step 1: Write the failing distribution-boundary test**

```python
from scripts.build_openclaw import build


def test_build_excludes_development_and_builder_files(tmp_path):
    output = tmp_path / "openclaw"
    build(output)

    assert (output / "SKILL.md").is_file()
    assert (output / "scripts" / "write_article.py").is_file()
    assert (output / "references" / "knowledge-corpus.yaml").is_file()
    assert not (output / "scripts" / "build_openclaw.py").exists()
    assert not (output / "scripts" / "migrate_web_state_to_d1.py").exists()
    assert not (output / "references" / "plans").exists()
    assert not (output / "references" / "specs").exists()
```

- [ ] **Step 2: Run the test and confirm the current builder violates the boundary**

Run: `python3 -m pytest tests/test_build_openclaw.py -q`

Expected: FAIL because `scripts/build_openclaw.py`, `references/plans`, or `references/specs` is copied.

- [ ] **Step 3: Add explicit build exclusions**

In `scripts/build_openclaw.py`, replace the inline ignore list with constants and include exactly these patterns:

```python
COPY_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "migrate_web_state_to_d1.py",
    "build_openclaw.py",
    "plans",
    "specs",
)
```

Pass `shutil.ignore_patterns(*COPY_IGNORE_PATTERNS)` to every copied directory.

- [ ] **Step 4: Run the focused test**

Run: `python3 -m pytest tests/test_build_openclaw.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the distribution boundary**

```bash
git add scripts/build_openclaw.py tests/test_build_openclaw.py
git commit -m "test: enforce OpenClaw distribution boundary"
```

### Task 2: Remove Demonstrably Dead Source and Dependencies

**Files:**
- Create: `tests/test_repository_structure.py`
- Delete: `scripts/seo_keywords.py`
- Delete: `toolkit/fix_image_paths.py`
- Delete: `toolkit/normalize_image.py`
- Modify: `scripts/build_topic_patterns.py`
- Modify: `scripts/diagnose.py`
- Modify: `scripts/expand_corpus.py`
- Modify: `scripts/fetch_stats.py`
- Modify: `scripts/humanness_score.py`
- Modify: `scripts/keyword_research.py`
- Modify: `scripts/learn_edits.py`
- Modify: `scripts/learn_theme.py`
- Modify: `scripts/write_article.py`
- Modify: `toolkit/converter.py`
- Modify: `toolkit/theme.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: the existing public CLI and module interfaces not named for deletion.
- Produces: the same public runtime behavior without obsolete files, unreachable helpers, or `cssutils`.

- [ ] **Step 1: Write the failing repository-structure test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_obsolete_source_and_dependency_are_absent():
    obsolete = [
        ROOT / "scripts" / "seo_keywords.py",
        ROOT / "toolkit" / "fix_image_paths.py",
        ROOT / "toolkit" / "normalize_image.py",
    ]
    assert not [path for path in obsolete if path.exists()]
    assert "cssutils" not in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "cssutils" not in (ROOT / "scripts" / "diagnose.py").read_text(encoding="utf-8").lower()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python3 -m pytest tests/test_repository_structure.py -q`

Expected: FAIL listing the three existing obsolete files.

- [ ] **Step 3: Delete obsolete files and unreachable helpers**

Delete the three files listed above. Remove:

- `fetch_article_total` from `scripts/fetch_stats.py`;
- `_load_from_file` and the obsolete `--file` usage line from `scripts/learn_theme.py`;
- `_resolve_css_variables`, `_is_simple_selector`, and `get_inline_css_rules` from `toolkit/theme.py`.

Do not remove compatibility functions listed under Global Constraints.

- [ ] **Step 4: Remove unused imports and dependency declarations**

Remove imports reported unused by the AST audit:

- `Counter` from `scripts/build_topic_patterns.py`;
- `sys` from `scripts/expand_corpus.py` and `scripts/humanness_score.py`;
- `json` from `scripts/fetch_stats.py` and the local import in `scripts/write_article.py`;
- `Optional` from `scripts/keyword_research.py`, `toolkit/converter.py`, and `toolkit/theme.py`;
- `timedelta` from `scripts/learn_edits.py`;
- imports made obsolete by the removed theme parser: `logging`, `re`, and `cssutils`.

Remove `cssutils>=2.9` from `requirements.txt` and `("cssutils", "cssutils")` from `scripts/diagnose.py`.

- [ ] **Step 5: Run focused and full tests**

Run: `python3 -m pytest tests/test_repository_structure.py tests/test_image_gen.py tests/test_keyword_research.py -q`

Expected: all focused tests pass.

Run: `python3 -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit dead-code removal**

```bash
git add requirements.txt scripts toolkit tests/test_repository_structure.py
git commit -m "refactor: remove obsolete utilities and dead code"
```

### Task 3: Remove Historical Documents and Regenerate Distribution

**Files:**
- Delete: all old files under `docs/superpowers/plans/`
- Preserve: `docs/superpowers/plans/2026-09-02-dead-code-and-structure-cleanup.md`
- Delete: all old files under `docs/superpowers/specs/`
- Preserve: `docs/superpowers/specs/2026-09-02-dead-code-and-structure-cleanup-design.md`
- Delete: `references/plans/`
- Delete: `references/specs/`
- Modify: `README.md`
- Regenerate: `dist/openclaw/`

**Interfaces:**
- Consumes: the cleaned source tree and `scripts.build_openclaw.build`.
- Produces: runtime-only `references/`, current-only development documentation, and synchronized `dist/openclaw/`.

- [ ] **Step 1: Delete only the approved historical documents**

Remove every tracked historical plan/spec file except the two current 2026-09-02 documents named above. Remove the now-empty `references/plans` and `references/specs` directories. Do not delete any other file beneath `references/` or `docs/`.

- [ ] **Step 2: Update the README directory overview**

Describe:

- `references/` as runtime knowledge and writing instructions;
- `docs/superpowers/` as the location for the current design and implementation plan;
- `dist/openclaw/` as a generated runtime-only distribution.

- [ ] **Step 3: Regenerate the checked-in distribution**

Run: `python3 scripts/build_openclaw.py`

Expected: build completes; deleted utilities and historical `references/plans` and `references/specs` disappear from `dist/openclaw`; the builder itself is absent from the output.

- [ ] **Step 4: Verify source/distribution structure**

Run: `python3 -m pytest tests/test_build_openclaw.py tests/test_repository_structure.py -q`

Expected: all structure tests pass.

Run searches excluding the current plan/spec:

```bash
rg -n "image-1---|fetch_article_total|_load_from_file|get_inline_css_rules|seo_keywords" \
  --glob '!dist/**' \
  --glob '!docs/superpowers/plans/2026-09-02-dead-code-and-structure-cleanup.md' \
  --glob '!docs/superpowers/specs/2026-09-02-dead-code-and-structure-cleanup-design.md' .
```

Expected: no matches.

- [ ] **Step 5: Run final verification**

Run: `python3 -m pytest -q`

Expected: all tests pass.

Run: `python3 -m compileall -q toolkit scripts webapp`

Expected: exit 0.

Run: `docker compose config -q`

Expected: exit 0.

Run: `python3 scripts/build_openclaw.py -o /tmp/wechat-studio-openclaw-check`

Expected: exit 0 with runtime files only.

Run: `git diff --check`

Expected: exit 0.

- [ ] **Step 6: Commit structure cleanup and regenerated distribution**

```bash
git add -A README.md docs references dist scripts toolkit requirements.txt tests
git commit -m "refactor: streamline project structure"
```
