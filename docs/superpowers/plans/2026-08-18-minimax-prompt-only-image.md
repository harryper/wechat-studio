# MiniMax Prompt-Only Artwork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce MiniMax pseudo-text through scene-focused prompts while restoring five real images whenever the image API succeeds.

**Architecture:** `webapp/render.py` builds five role-specific cinematic scene prompts and accepts every successful provider response. `toolkit/image_gen.py` returns to simple provider fallback with no OCR validator or quality rejection. Docker and distributable artifacts remove Tesseract while preserving the provider `enabled` switch and OpenAI's default-off configuration.

**Tech Stack:** Python 3, requests, Pillow, pytest, YAML, Docker.

## Global Constraints

- Image quality is manually reviewed in the workbench; no OCR or automatic text rejection remains.
- MiniMax API success always produces a `real` image state.
- Only provider/API failure may produce a PIL placeholder.
- OpenAI remains disabled by default and must not incur API charges.
- Historical images and diagnostic files are not migrated or deleted.
- `todo.md` is user-owned, untracked, and must not be modified or committed.
- Source and `dist/openclaw` must remain synchronized.

---

### Task 1: Replace explanatory prompts with cinematic scenes

**Files:**
- Modify: `webapp/render.py:68-125`
- Modify: `tests/test_webapp_render.py`

**Interfaces:**
- Consumes: topic dictionaries containing `title`, `category`, and `key_points`.
- Produces: `_cover_prompt(topic: dict) -> str` and `_inline_prompts(topic: dict) -> list[str]`.
- Preserves: exactly one cover prompt and four inline prompts.

- [ ] **Step 1: Write failing scene-prompt tests**

Replace the old style assertions with these explicit contracts:

```python
TEXT_INDUCING_TERMS = [
    "学术插画", "编辑插画", "概念图", "机制图", "线稿说明图",
    "流程图", "信息图", "标题区域", "文字区域",
]

def test_prompts_use_single_focus_cinematic_scenes():
    for prompt in _all_prompts(TOPIC):
        assert "电影感场景" in prompt
        assert "单一视觉焦点" in prompt
        assert "具体动作" in prompt
        for term in TEXT_INDUCING_TERMS:
            assert term not in prompt

def test_cover_uses_natural_negative_space_not_title_area():
    prompt = render._cover_prompt(TOPIC)
    assert "天空、墙面、雾气或暗部" in prompt
    assert "标题区域" not in prompt and "文字区域" not in prompt

def test_inline_prompts_have_distinct_scene_contracts():
    prompts = render._inline_prompts(TOPIC)
    assert "人物正在完成一个具体动作" in prompts[0]
    assert "两至三个真实物体" in prompts[1]
    assert "人物与实体器材互动" in prompts[2]
    assert "现实生活场景" in prompts[3]
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python3 -m pytest -q tests/test_webapp_render.py -k 'prompt or scene'`

Expected: FAIL because current prompts contain `学术插画` and `编辑插画` and lack the four scene contracts.

- [ ] **Step 3: Implement the shared scene constraint**

Use this runtime suffix for all five prompts:

```python
_SCENE_CONSTRAINT = (
    "电影感场景，横版构图，单一视觉焦点，主体正在完成一个具体动作；"
    "主题词仅用于理解含义，绝不能以字符形式画进图片。"
    "画面不得出现标题、段落、字母、汉字、数字、水印、logo、箭头、路线、"
    "流程节点、标签、图例、表格、图表、书页、文件、标牌、屏幕、设备界面或海报布局。"
    "purely visual cinematic scene, one focal subject performing a concrete action, "
    "no text, letters, words, numbers, captions, labels, signs, screens, documents, "
    "charts, arrows, diagrams, UI, logos, watermarks or poster layout"
)
```

Build the cover as one conflict-bearing physical metaphor with blank sky, wall, fog, or shadow. Build inline roles as: historical human action; two-to-three physical objects; human interacting with physical experiment equipment; and a real-life application scene without phones or computers. Keep topic/key points as semantic context, without quoting them.

- [ ] **Step 4: Run the prompt tests and verify GREEN**

Run: `python3 -m pytest -q tests/test_webapp_render.py -k 'prompt or scene'`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/render.py tests/test_webapp_render.py
git commit -m "fix: use cinematic scenes for minimax artwork"
```

### Task 2: Remove OCR rejection and restore API-success semantics

**Files:**
- Modify: `toolkit/image_gen.py`
- Modify: `webapp/render.py:293-412`
- Modify: `tests/test_image_gen.py`
- Modify: `tests/test_webapp_render.py`
- Modify: `Dockerfile:10-17`

**Interfaces:**
- Restores: `generate_image(prompt: str, output_path: str, size: str = "cover", config: dict | None = None) -> str`.
- Removes: `detect_text`, `validator`, `attempts_per_provider`, `diagnostics`, `_RETRY_NO_TEXT_SUFFIX`, and Web OCR diagnostic helpers.
- Preserves: `_config_enabled`, provider fallback, resizing, compression, and provider `enabled` handling.

- [ ] **Step 1: Write a failing Web acceptance test**

```python
def test_generate_images_accepts_every_successful_provider_result(tmp_path, monkeypatch):
    workdir = tmp_path / "work"
    (workdir / "images").mkdir(parents=True)
    calls = []

    def fake_generate(prompt, output, size):
        calls.append((prompt, Path(output).name, size))
        Path(output).write_bytes(b"real")

    monkeypatch.setattr(render, "generate_image", fake_generate)
    mode = render.generate_images_in_workdir(
        workdir, TOPIC, render.default_image_rels()
    )
    assert mode == "real"
    assert len(calls) == 5
    states = json.loads((workdir / "image-status.json").read_text())
    assert set(states.values()) == {"real"}
    assert not (workdir / "image-diagnostics.json").exists()
```

Keep the mixed-mode test proving one raised API exception creates one placeholder.

- [ ] **Step 2: Run the Web tests and verify RED**

Run: `python3 -m pytest -q tests/test_webapp_render.py -k 'generate_images or diagnostics or validation'`

Expected: FAIL because Web still passes OCR kwargs and writes diagnostics.

- [ ] **Step 3: Remove OCR wiring from Web**

Import only `generate_image`. Delete `_ATTEMPTS_PER_PROVIDER`, `_write_image_diagnostics`, and `_read_image_diagnostics`. In both full and single regeneration call only `generate_image(prompt, target, size=...)`. Continue writing `image-status.json` with the existing compatibility values.

- [ ] **Step 4: Replace OCR tests with provider fallback tests**

Delete all Tesseract, validator, rejection, retry-suffix, and OCR diagnostic tests. Retain provider enable/disable tests and add:

```python
import inspect

def test_generate_image_has_simple_public_signature():
    assert list(inspect.signature(image_gen.generate_image).parameters) == [
        "prompt", "output_path", "size", "config",
    ]

def test_generate_image_accepts_first_successful_provider_bytes(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [b"image-with-any-content"])
    fallback = FakeProvider("openai", [b"never"])
    fake_chain(minimax, fallback)
    out = tmp_path / "cover.jpg"
    image_gen.generate_image("prompt", str(out), config={})
    assert out.read_bytes() == b"image-with-any-content"
    assert fallback.prompts == []

def test_generate_image_falls_back_after_provider_exception(tmp_path, fake_chain):
    minimax = FakeProvider("minimax", [RuntimeError("quota")])
    fallback = FakeProvider("fallback", [b"clean"])
    fake_chain(minimax, fallback)
    out = tmp_path / "cover.jpg"
    image_gen.generate_image("prompt", str(out), config={})
    assert out.read_bytes() == b"clean"
```

- [ ] **Step 5: Run provider tests and verify RED**

Run: `python3 -m pytest -q tests/test_image_gen.py`

Expected: `test_generate_image_has_simple_public_signature` FAILS because the OCR-related parameters still exist.

- [ ] **Step 6: Restore the simple provider loop**

Remove `subprocess` and all OCR constants/functions. Remove quality-control parameters from `generate_image`. Call each enabled provider once; accept and write every successful byte response; catch exceptions and continue to the next enabled provider. Raise `All providers failed` only if every provider raises.

- [ ] **Step 7: Remove Tesseract from Docker**

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 8: Run focused tests and verify GREEN**

Run: `python3 -m pytest -q tests/test_image_gen.py tests/test_webapp_render.py`

Expected: all focused tests PASS.

- [ ] **Step 9: Commit**

```bash
git add Dockerfile toolkit/image_gen.py webapp/render.py tests/test_image_gen.py tests/test_webapp_render.py
git commit -m "refactor: remove automatic artwork ocr gate"
```

### Task 3: Synchronize instructions and distribution

**Files:**
- Modify: `SKILL.md`
- Modify: `references/visual-prompts.md`
- Modify: `config.example.yaml` only if it contains removed OCR behavior
- Regenerate: `dist/openclaw/`

**Interfaces:**
- Documents: manual preview review and single-image regeneration.
- Preserves: OpenAI `enabled: "${OPENAI_IMAGE_ENABLED:-false}"` examples.

- [ ] **Step 1: Remove automatic OCR claims**

Run:

```bash
rg -n "OCR|Tesseract|文字检测|自动拒绝|质量重试|candidate rejected|image-diagnostics" \
  SKILL.md references config.example.yaml
```

Replace matches with the actual workflow: MiniMax prompts avoid text-inducing layouts; the user inspects the preview and regenerates individual images as needed. Keep the existing no-text prompt guidance.

- [ ] **Step 2: Regenerate the OpenClaw distribution**

Run: `python3 scripts/build_openclaw.py`

Expected: exit 0 and generated files mirror source.

- [ ] **Step 3: Verify source/distribution synchronization**

Run:

```bash
cmp toolkit/image_gen.py dist/openclaw/toolkit/image_gen.py
cmp references/visual-prompts.md dist/openclaw/references/visual-prompts.md
rg -n "tesseract|detect_text|image-diagnostics" Dockerfile toolkit webapp dist/openclaw
```

Expected: both `cmp` commands exit 0; the final search has no production/distribution matches.

- [ ] **Step 4: Run full verification**

Run:

```bash
python3 -m pytest -q
git diff --check
python3 -c "from toolkit.image_gen import _build_provider_chain,_load_config; keys=[p.provider_key for p in _build_provider_chain(_load_config())]; print(keys); assert keys == ['minimax']"
```

Expected: all tests PASS, diff check is silent, and provider chain is `['minimax']`.

- [ ] **Step 5: Build Docker and prove Tesseract is absent**

Run:

```bash
docker compose build wechat-studio-web
docker compose run --rm --no-deps wechat-studio-web sh -c \
  'if command -v tesseract; then exit 1; else echo "tesseract absent"; fi'
```

Expected: build exits 0 and the one-off container prints `tesseract absent`.

- [ ] **Step 6: Confirm user-owned files remain untouched**

Run: `git status --short`

Expected: `todo.md` remains `?? todo.md` and is not staged.

- [ ] **Step 7: Commit**

```bash
git add SKILL.md references/visual-prompts.md dist/openclaw
git commit -m "docs: document manual minimax artwork review"
```

Add `config.example.yaml` only if it has a relevant diff.

### Task 4: Deploy and smoke-test

**Files:**
- No source changes.

**Interfaces:**
- Deploys: `wechat-studio-web` from the rebuilt image.
- Verifies: healthy service and MiniMax-only provider chain.

- [ ] **Step 1: Recreate the service**

Run: `docker compose up -d --build wechat-studio-web`

Expected: container is recreated and started.

- [ ] **Step 2: Verify runtime health**

Run:

```bash
docker compose ps --format json
curl -fsS -m 5 http://127.0.0.1:9997/api/health
docker compose exec -T wechat-studio-web python -c "from toolkit.image_gen import _build_provider_chain,_load_config; print([p.provider_key for p in _build_provider_chain(_load_config())])"
```

Expected: service is healthy, health JSON contains `"ok":true`, and provider list is `['minimax']`.

- [ ] **Step 3: Hand off manual visual verification**

Ask the user to refresh the workbench and run “重生全部图片” for topic `custom-3abc6bcd-b2ab-4b19-8e4b-6c664cecac13`. Five successful MiniMax responses must remain real images; the user evaluates remaining pseudo-text and uses “重生指定图片” where needed.
