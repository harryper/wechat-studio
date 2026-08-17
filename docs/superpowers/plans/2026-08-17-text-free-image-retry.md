# Text-Free Image Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent pseudo-text in generated WeChat artwork without adding paid OpenAI API usage.

**Architecture:** Runtime prompts describe pictorial scenes and append a shared bilingual no-text constraint. `toolkit/image_gen.py` validates candidate bytes with optional local Tesseract OCR, retries the same provider with a stronger prompt, and only then follows the enabled provider chain. Web rendering records provider/validation diagnostics while preserving existing aggregate statuses.

**Tech Stack:** Python 3, Pillow, requests, pytest, Tesseract CLI, YAML.

## Global Constraints

- OpenAI remains disabled by default and must require an explicit `OPENAI_IMAGE_ENABLED=true` opt-in.
- No cloud OCR or new paid service.
- Existing `real`, `mixed`, and `placeholder` Web API results remain compatible.
- Missing Tesseract skips OCR with an explicit `not_available` diagnostic.
- Existing historical images are not regenerated automatically.

---

### Task 1: Runtime text-free prompts

**Files:**
- Modify: `webapp/render.py:68-101`
- Test: `tests/test_webapp_render.py`

**Interfaces:**
- Consumes: topic dictionaries with `title`, `category`, and `key_points`.
- Produces: `_cover_prompt(topic) -> str` and `_inline_prompts(topic) -> list[str]` with no quoted title and a shared hard constraint.

- [ ] **Step 1: Write failing prompt tests**

Add tests asserting that cover/inline prompts omit `「` and `」`, contain `no text, no letters, no words, no numbers`, and prohibit labels, logos, watermarks, signs, book pages, screens, charts, and poster layouts. Assert the visual topic remains present as semantic context.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/test_webapp_render.py -k 'prompt'`

Expected: FAIL because current prompts contain book-title brackets and only the short Chinese phrase `无文字`.

- [ ] **Step 3: Implement minimal prompt builder**

Add `_NO_TEXT_CONSTRAINT` and `_pictorial_subject(text)` helpers. Build prompts as concrete editorial illustrations, avoid infographic/diagram/chart/poster language, preserve clean cover negative space, and append the same bilingual hard constraint to all five prompts.

- [ ] **Step 4: Run prompt tests and verify GREEN**

Run: `pytest -q tests/test_webapp_render.py -k 'prompt'`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/render.py tests/test_webapp_render.py
git commit -m "fix: generate strictly text-free artwork prompts"
```

### Task 2: Local OCR validation and same-provider retry

**Files:**
- Modify: `toolkit/image_gen.py:659-755`
- Create: `tests/test_image_gen.py`
- Modify: `Dockerfile`

**Interfaces:**
- Produces: `detect_text(raw_bytes: bytes) -> tuple[str, str]`, where status is `pass`, `rejected`, or `not_available` and detail is safe diagnostic text.
- Extends: `generate_image(..., validator=None, attempts_per_provider=1, diagnostics=None) -> str` without breaking existing callers.
- Provider config entry `enabled` accepts booleans and `false`, `0`, `no`, or `off` strings.

- [ ] **Step 1: Write failing tests for disabled providers**

Create fake provider entries and assert `_build_provider_chain` skips `enabled: false` and `${OPENAI_IMAGE_ENABLED:-false}` after config expansion.

- [ ] **Step 2: Run disabled-provider test and verify RED**

Run: `pytest -q tests/test_image_gen.py -k 'disabled_provider'`

Expected: FAIL because `_build_provider_chain` currently ignores `enabled`.

- [ ] **Step 3: Implement enabled parsing**

Add `_config_enabled(value) -> bool` and skip disabled entries before `_build_provider_from_entry`.

- [ ] **Step 4: Write failing OCR parser tests**

Monkeypatch `subprocess.run` with Tesseract TSV output. Assert 12 or more high-confidence alphanumeric characters return `rejected`, sparse/no tokens return `pass`, and `FileNotFoundError` returns `not_available`.

- [ ] **Step 5: Run OCR tests and verify RED**

Run: `pytest -q tests/test_image_gen.py -k 'detect_text'`

Expected: FAIL because `detect_text` does not exist.

- [ ] **Step 6: Implement local Tesseract detection**

Run `tesseract stdin stdout --psm 11 tsv` with candidate bytes on stdin, parse confidence/text columns, and reject at 12 high-confidence alphanumeric characters. Never include OCR text in diagnostics.

- [ ] **Step 7: Write failing retry tests**

Use fake providers returning distinct byte strings. Assert validator rejection causes a second call to the same provider with the strengthened retry constraint; a pass writes the second bytes; exhausting attempts advances only to enabled fallback providers; all rejections raise a message containing `quality validation rejected`.

- [ ] **Step 8: Run retry tests and verify RED**

Run: `pytest -q tests/test_image_gen.py -k 'retry or validation'`

Expected: FAIL because `generate_image` currently performs one unvalidated attempt per provider.

- [ ] **Step 9: Implement retry and diagnostics**

Add optional arguments, call validator before writing, append an even stronger no-text retry suffix for attempt 2+, and populate diagnostics with provider key, attempts, validation status, and safe rejection reasons.

- [ ] **Step 10: Install Tesseract in Docker and verify GREEN**

Add `tesseract-ocr` and `tesseract-ocr-eng` to the existing apt install layer without adding Python OCR packages.

Run: `pytest -q tests/test_image_gen.py`

Expected: all tests PASS.

- [ ] **Step 11: Commit**

```bash
git add Dockerfile toolkit/image_gen.py tests/test_image_gen.py
git commit -m "feat: reject text-heavy image candidates locally"
```

### Task 3: Web diagnostics and no-cost configuration

**Files:**
- Modify: `webapp/render.py:271-340`
- Modify: `tests/test_webapp_render.py`
- Modify: `config.yaml`
- Modify: `config.example.yaml`
- Modify: `dist/openclaw/toolkit/image_gen.py`
- Modify: `dist/openclaw/config.example.yaml`
- Modify: `dist/openclaw/SKILL.md`
- Modify: `dist/openclaw/references/visual-prompts.md`

**Interfaces:**
- Consumes: `generate_image(..., validator=detect_text, attempts_per_provider=2, diagnostics=dict)`.
- Produces: `image-diagnostics.json` keyed by image role; never stores keys, full prompts, OCR text, or provider responses.

- [ ] **Step 1: Write failing Web diagnostics tests**

Update fake `generate_image` functions to accept keyword arguments. Assert each call receives `detect_text` and two attempts, and that `image-diagnostics.json` contains only provider, attempt count, validation status, and safe reasons for all five roles.

- [ ] **Step 2: Run Web tests and verify RED**

Run: `pytest -q tests/test_webapp_render.py -k 'generate_images or diagnostics'`

Expected: FAIL because the Web renderer does not pass validation options or write diagnostics.

- [ ] **Step 3: Implement Web wiring**

Import `detect_text`, pass validation/retry arguments for full and single-image generation, write diagnostics atomically beside `image-status.json`, and preserve existing `real`/`mixed`/`placeholder` calculations.

- [ ] **Step 4: Disable OpenAI by default**

Set the OpenAI entry in `config.yaml` to `enabled: ${OPENAI_IMAGE_ENABLED:-false}` and document the same opt-in in `config.example.yaml`. Do not remove provider support or API key expansion.

- [ ] **Step 5: Synchronize distributable files**

Run the repository's existing build script so `dist/openclaw/` mirrors the changed source, config example, skill instructions, and visual prompt guidance.

Run: `python3 scripts/build_openclaw.py`

Expected: command exits 0 and the generated files contain the no-text constraints and provider enable flag.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest -q tests/test_webapp_render.py tests/test_image_gen.py`

Expected: all selected tests PASS.

- [ ] **Step 7: Run full verification**

Run: `pytest -q`

Expected: entire suite PASS with zero failures.

Run: `git diff --check`

Expected: exit 0 with no output.

- [ ] **Step 8: Commit**

```bash
git add config.yaml config.example.yaml webapp/render.py tests/test_webapp_render.py dist/openclaw
git commit -m "feat: add no-cost image quality retry pipeline"
```
