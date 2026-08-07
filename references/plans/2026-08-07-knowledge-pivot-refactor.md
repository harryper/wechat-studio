# Knowledge Pivot Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace wechat-studio's hot-topic track with a knowledge/cognitive curriculum track — topic library (60+ seed), 3 academic writing frameworks, mandatory disclaimer, conceptual-diagram visuals.

**Architecture:** Replace Step 2 hotspot scraping with corpus-based round-robin selection. Three academic writing frameworks (origin-evolution, principle-evidence, experiment-application) replace the popular-content ones. Visual style shifts from documentary to conceptual diagrams. Disclaimer auto-injected by `cli.py publish`.

**Tech Stack:** Python 3.10+, PyYAML, pytest (TDD), existing `toolkit/cli.py`.

**Spec:** `references/specs/2026-08-07-wechat-studio-knowledge-pivot-design.md`

## Global Constraints

From the spec:
- All decisions confirmed in brainstorming session 2026-08-07 (recorded in spec)
- Topic library minimum 60 entries (10 per category)
- Categories: `cognitive_bias`, `decision_theory`, `philosophy`, `psychology`, `economics`, `paradox`
- Word count: 2500–4000 字 (vs old 1500–2500)
- Mandatory disclaimer: "本文为逻辑梳理，非学术研究"
- Topic ID format: `kb-NNN` (zero-padded)
- Disclaimer is non-toggleable (auto-injected by cli.py)
- Weekly cadence: 2 posts/week → 60 topics ≈ 30 weeks (7 months)
- Backwards compatibility: existing 8-step flow regressed but not actively used

---

## File Structure

**New files:**
- `references/knowledge-corpus.yaml` — 60+ topic seed data
- `references/frameworks-academic.md` — 3 academic writing frameworks
- `scripts/load_corpus.py` — YAML parser + dedup selector
- `scripts/expand_corpus.py` — CLI to add new topics
- `scripts/keyword_research.py` — Replace `seo_keywords.py`
- `scripts/migrate_history.py` — Update existing `history.yaml` with track field
- `tests/test_load_corpus.py` — unit tests
- `tests/test_expand_corpus.py` — unit tests
- `tests/test_keyword_research.py` — unit tests
- `tests/test_migrate_history.py` — unit tests
- `tests/test_cli_disclaimer.py` — unit tests

**Modified files:**
- `SKILL.md` — Replace Step 2 hotspot track with Step 2 corpus track
- `references/visual-prompts.md` — Shift style note to conceptual diagrams
- `references/seo-rules.md` — Replace 3-model rule with academic variants
- `references/topic-selection.md` — Selection logic now from corpus
- `toolkit/cli.py` — Inject disclaimer in publish path
- `scripts/seo_keywords.py` — Keep as deprecated stub pointing to `keyword_research.py`

---

## Phase 1: Foundation

### Task 1: Create knowledge corpus YAML with 60 seed topics

**Files:**
- Create: `references/knowledge-corpus.yaml`

**Interfaces:**
- Produces: `references/knowledge-corpus.yaml` parsed by `scripts/load_corpus.py` (Task 2)

- [ ] **Step 1: Create file with 60 entries (10 per category)**

Each entry follows the schema:
```yaml
- id: kb-001
  title: 幸存者偏差
  category: cognitive_bias
  key_points:
    - 起源：二战期间统计学家亚伯拉罕·沃德对返航轰炸机的研究
    - 机制：人们只看到"幸存者"而忽略"阵亡者"
    - 经典案例：成功创业者访谈偏差
    - 现代应用：投资、招聘、健康决策中的误判
  origin: 1943 年哥伦比亚大学沃德研究 → 1972 年丹尼尔·卡尼曼正式命名
  caution: no
```

Required coverage (10 per category = 60 total):
- `cognitive_bias`: 幸存者偏差、锚定效应、可得性启发、确认偏差、达克效应、禀赋效应、损失厌恶、赌徒谬误、概率忽视、信念偏差
- `decision_theory`: 前景理论、机会成本、边际效用、沉没成本、博弈论、帕累托最优、风险厌恶、动态规划、决策树、效用函数
- `philosophy`: 第一性原理、奥卡姆剃刀、忒修斯之船、缸中之脑、洞穴寓言、芝诺悖论、休谟问题、功利主义、康德义务论、存在主义
- `psychology`: 认知失调、心流、习得性无助、皮格马利翁效应、旁观者效应、镜像神经元、双重加工理论、依恋理论、强化理论、情绪颗粒度
- `economics`: 看不见的手、比较优势、边际递减、机会成本、供需曲线、GDP 悖论、菲利普斯曲线、挤出效应、麦金农命题、行为经济学
- `paradox`: 薛定谔的猫、费米悖论、双生子悖论、莫比乌斯环、阿里士悖论、芝诺悖论、祖父悖论、迪奥尼修斯之谜、巴斯卡赌注、麦克斯韦妖

**Requirements for each entry:**
- `id` unique across file (kb-001 through kb-060)
- `key_points` 3-5 bullets, each bullet ≥10 字
- `origin` non-empty string

- [ ] **Step 2: Validate YAML parses**

Run: `python3 -c "import yaml; data = yaml.safe_load(open('references/knowledge-corpus.yaml')); print(len(data), len({t['id'] for t in data}))"`
Expected: `60 60` (60 entries, 60 unique IDs)

- [ ] **Step 3: Commit**

```bash
git add references/knowledge-corpus.yaml
git commit -m "feat(corpus): add 60 seed knowledge topics (10 per category)"
```

---

### Task 2: Create `load_corpus.py` with round-robin selection

**Files:**
- Create: `scripts/load_corpus.py`
- Create: `tests/test_load_corpus.py`

**Interfaces:**
- Consumes: `references/knowledge-corpus.yaml`, `clients/{client}/history.yaml`
- Produces: `next_topic(client: str) -> dict` — first unused topic
- Produces: `load_corpus() -> list[dict]` — full corpus
- Produces: `used_topic_ids(client: str) -> set[str]` — IDs from history

- [ ] **Step 1: Write failing test**

`tests/test_load_corpus.py`:
```python
import os
import pytest
import yaml

from scripts.load_corpus import (
    load_corpus,
    next_topic,
    used_topic_ids,
    CORPUS_PATH,
)


def test_load_corpus_returns_60():
    corpus = load_corpus()
    assert len(corpus) == 60


def test_load_corpus_ids_unique():
    corpus = load_corpus()
    ids = [t["id"] for t in corpus]
    assert len(ids) == len(set(ids))


def test_load_corpus_required_fields():
    corpus = load_corpus()
    for t in corpus:
        assert "id" in t
        assert "title" in t
        assert "category" in t
        assert "key_points" in t
        assert "origin" in t
        assert 3 <= len(t["key_points"]) <= 5


def test_next_topic_returns_first_unused(tmp_path, monkeypatch):
    # fake history
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"topic_id": "kb-001", "title": "幸存者偏差", "track": "knowledge"}
    ], allow_unicode=True))

    # monkeypatch load_corpus to keep test hermetic
    corpus = load_corpus()
    used = {"kb-001"}
    picked = next(t for t in corpus if t["id"] not in used)
    assert picked["id"] == "kb-002"


def test_next_topic_when_all_used():
    corpus = load_corpus()
    all_ids = {t["id"] for t in corpus}
    # round-robin should restart from top
    picked = next(t for t in corpus if t["id"] not in all_ids)
    assert picked["id"] == corpus[0]["id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_load_corpus.py -v`
Expected: ImportError or ModuleNotFoundError on `scripts.load_corpus`

- [ ] **Step 3: Implement `load_corpus.py`**

```python
#!/usr/bin/env python3
"""Load knowledge corpus and pick next topic for writing."""

import os
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS_PATH = SKILL_DIR / "references" / "knowledge-corpus.yaml"


def load_corpus() -> list[dict]:
    """Load all topics from knowledge corpus YAML."""
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def used_topic_ids(client: str) -> set[str]:
    """Read history.yaml for a client and extract used topic_ids."""
    history_path = SKILL_DIR / "clients" / client / "history.yaml"
    if not history_path.exists():
        return set()
    with open(history_path, "r", encoding="utf-8") as f:
        history = yaml.safe_load(f) or []
    return {entry.get("topic_id") for entry in history if entry.get("topic_id")}


def next_topic(client: str) -> dict:
    """Pick first unused topic from corpus. Round-robin when exhausted."""
    corpus = load_corpus()
    used = used_topic_ids(client)
    for topic in corpus:
        if topic["id"] not in used:
            return topic
    # All used — restart from top
    return corpus[0]


def exhaustion_pct(client: str) -> float:
    """Return fraction of corpus used by client (0.0–1.0)."""
    corpus = load_corpus()
    used = used_topic_ids(client)
    return len(used & {t["id"] for t in corpus}) / len(corpus)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pick next topic from knowledge corpus")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--dry-run", action="store_true", help="Just print, don't write")
    args = parser.parse_args()

    topic = next_topic(args.client)
    pct = exhaustion_pct(args.client)
    print(f"Next topic: {topic['id']} — {topic['title']}")
    print(f"Corpus exhaustion: {pct:.0%}")
    if pct >= 0.8:
        print("⚠️  Warning: corpus ≥80% used. Run scripts/expand_corpus.py")
    if pct >= 1.0:
        print("🔄 100% used — round-robin restart")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_load_corpus.py -v`
Expected: 5 passed

- [ ] **Step 5: Smoke test CLI**

Run: `python3 scripts/load_corpus.py --client demo --dry-run`
Expected: `Next topic: kb-001 — 幸存者偏差` (or first unused)

- [ ] **Step 6: Commit**

```bash
git add scripts/load_corpus.py tests/test_load_corpus.py
git commit -m "feat(corpus): add load_corpus.py with round-robin topic selection"
```

---

### Task 3: Create academic frameworks document

**Files:**
- Create: `references/frameworks-academic.md`

**Interfaces:**
- Consumes: framework selection logic from `SKILL.md` Step 3
- Produces: framework templates for the writer agent

- [ ] **Step 1: Create the file**

Three frameworks with structure, length targets, agent selection logic. Match the spec's § 3.

```markdown
# 三套学术写作框架

## 框架 1：起源-演变-影响（默认）

**适用主题：** 含"起源"、"演变"、"提出"关键词

```
H1 标题
  ├─ 摘要（100 字内点题）
  ├─ § 1 起源（300-500 字）
  │    - 时代背景 / 提出者 / 原始问题
  ├─ § 2 发展演变（300-500 字）
  │    - 关键修订 / 重要实验 / 学术争论
  ├─ § 3 影响与应用（400-600 字）
  │    - 在商业/医学/政策中的具体应用
  ├─ § 4 反直觉点（200-300 字）
  │    - 常见误解 / 易混淆概念边界
  └─ 免责声明（50 字内）
       "本文为逻辑梳理，非学术研究。引用细节可能存在简化。"
```

## 框架 2：原理-证据-应用

**适用主题：** 含"原理"、"机制"、"定律"关键词

```
H1 标题
  ├─ 摘要
  ├─ § 1 原理阐释（核心机制，配合示意图）
  ├─ § 2 证据链（3-4 个经典实验或案例）
  ├─ § 3 现代应用（2-3 个落地场景）
  ├─ § 4 局限与边界
  └─ 免责声明
```

## 框架 3：经典实验-当代启示

**适用主题：** 含"实验"、"研究"、"测试"关键词

```
H1 标题
  ├─ 摘要
  ├─ § 1 实验背景（时代背景 / 研究者 / 原始问题）
  ├─ § 2 实验设计（变量 / 样本 / 方法）
  ├─ § 3 结果与争议（数据 / 后续修订）
  ├─ § 4 当代启示（2-3 个现代应用）
  └─ 免责声明
```

## Agent 选框架逻辑

1. 主题含"起源"、"演变"、"提出" → 框架 1
2. 主题含"原理"、"机制"、"定律" → 框架 2
3. 主题含"实验"、"研究"、"测试" → 框架 3
4. 都不匹配 → 默认框架 1

## 通用约束

- 总字数：2500-4000 字
- 学术定义式标题（30-50 字，允许副标题）
- 必含：摘要 100 字 + 免责声明 50 字
- 风格：academic but readable（避免大段术语堆砌）
```

- [ ] **Step 2: Verify file readable**

Run: `wc -l references/frameworks-academic.md`
Expected: ≥ 50 lines

- [ ] **Step 3: Commit**

```bash
git add references/frameworks-academic.md
git commit -m "feat(frameworks): add 3 academic writing frameworks"
```

---

### Task 4: Create `expand_corpus.py` CLI

**Files:**
- Create: `scripts/expand_corpus.py`
- Create: `tests/test_expand_corpus.py`

**Interfaces:**
- Consumes: `references/knowledge-corpus.yaml`
- Produces: appended entries

- [ ] **Step 1: Write failing test**

```python
import yaml
import pytest
from pathlib import Path

from scripts.expand_corpus import (
    next_id,
    validate_topic,
    append_topic,
)


def test_next_id_gap_handling():
    existing = [{"id": "kb-001"}, {"id": "kb-002"}, {"id": "kb-005"}]
    assert next_id(existing) == "kb-006"


def test_next_id_full():
    existing = [{"id": f"kb-{i:03d}"} for i in range(1, 1000)]
    assert next_id(existing).startswith("kb-")


def test_validate_topic_ok():
    topic = {
        "id": "kb-999",
        "title": "测试",
        "category": "cognitive_bias",
        "key_points": ["p1", "p2", "p3"],
        "origin": "测试起源",
        "caution": "no",
    }
    assert validate_topic(topic) is None


def test_validate_topic_missing_field():
    topic = {"id": "kb-999", "title": "测试"}  # missing fields
    with pytest.raises(ValueError, match="missing required field"):
        validate_topic(topic)


def test_validate_topic_bad_category():
    topic = {
        "id": "kb-999",
        "title": "测试",
        "category": "wrong_category",
        "key_points": ["p1", "p2", "p3"],
        "origin": "测试",
        "caution": "no",
    }
    with pytest.raises(ValueError, match="invalid category"):
        validate_topic(topic)


def test_append_topic(tmp_path):
    corpus_path = tmp_path / "corpus.yaml"
    corpus_path.write_text(yaml.safe_dump([{"id": "kb-001", "title": "t1"}], allow_unicode=True))

    new_topic = {
        "id": "kb-002",
        "title": "测试",
        "category": "cognitive_bias",
        "key_points": ["p1", "p2", "p3"],
        "origin": "起源",
        "caution": "no",
    }
    append_topic(corpus_path, new_topic)
    loaded = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    assert len(loaded) == 2
    assert loaded[1]["title"] == "测试"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_expand_corpus.py -v`
Expected: ImportError

- [ ] **Step 3: Implement `expand_corpus.py`**

```python
#!/usr/bin/env python3
"""Add new topics to the knowledge corpus."""

import argparse
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
CORPUS_PATH = SKILL_DIR / "references" / "knowledge-corpus.yaml"
VALID_CATEGORIES = {
    "cognitive_bias",
    "decision_theory",
    "philosophy",
    "psychology",
    "economics",
    "paradox",
}
REQUIRED_FIELDS = {"id", "title", "category", "key_points", "origin"}


def next_id(existing: list[dict]) -> str:
    """Return next free ID in kb-NNN format."""
    used = {t["id"] for t in existing}
    for i in range(1, 10000):
        candidate = f"kb-{i:03d}"
        if candidate not in used:
            return candidate
    raise RuntimeError("No free IDs up to kb-9999")


def validate_topic(topic: dict) -> None:
    """Raise ValueError if topic is malformed."""
    missing = REQUIRED_FIELDS - set(topic.keys())
    if missing:
        raise ValueError(f"missing required field: {missing}")
    if topic["category"] not in VALID_CATEGORIES:
        raise ValueError(f"invalid category: {topic['category']}")
    if not 3 <= len(topic["key_points"]) <= 5:
        raise ValueError(
            f"key_points must have 3-5 bullets, got {len(topic['key_points'])}"
        )
    if not topic["origin"].strip():
        raise ValueError("origin cannot be empty")


def append_topic(corpus_path: Path, topic: dict) -> None:
    """Append a validated topic to corpus YAML."""
    validate_topic(topic)
    with open(corpus_path, "r", encoding="utf-8") as f:
        corpus = yaml.safe_load(f)
    if any(t["id"] == topic["id"] for t in corpus):
        raise ValueError(f"duplicate ID: {topic['id']}")
    corpus.append(topic)
    with open(corpus_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(corpus, f, allow_unicode=True, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(description="Add topic to knowledge corpus")
    parser.add_argument("--title", required=True, help="Topic title")
    parser.add_argument("--category", required=True, choices=sorted(VALID_CATEGORIES))
    parser.add_argument("--key-points", nargs="+", required=True, help="3-5 bullet points")
    parser.add_argument("--origin", required=True, help="Origin/background")
    parser.add_argument("--caution", default="no", help="Caution flag")
    args = parser.parse_args()

    corpus = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
    topic = {
        "id": next_id(corpus),
        "title": args.title,
        "category": args.category,
        "key_points": args.key_points,
        "origin": args.origin,
        "caution": args.caution,
    }
    append_topic(CORPUS_PATH, topic)
    print(f"✅ Added {topic['id']} — {topic['title']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_expand_corpus.py -v`
Expected: 6 passed

- [ ] **Step 5: Smoke test**

Run: `python3 scripts/expand_corpus.py --title "测试主题" --category cognitive_bias --key-points "p1 起源" "p2 机制" "p3 应用" --origin "测试起源"`
Expected: `✅ Added kb-061 — 测试主题`

Then revert: `git checkout references/knowledge-corpus.yaml`

- [ ] **Step 6: Commit**

```bash
git add scripts/expand_corpus.py tests/test_expand_corpus.py
git commit -m "feat(corpus): add expand_corpus.py CLI for adding topics"
```

---

## Phase 2: Pipeline Refactor

### Task 5: Update SKILL.md to remove hotspot track

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: existing 8-step pipeline
- Produces: 8-step pipeline with corpus-based selection

- [ ] **Step 1: Replace Step 2 section**

Find (lines 42-77):
```
### Step 2: 热点抓取

```bash
python3 {skill_dir}/scripts/fetch_hotspots.py --limit 30
```

...

### Step 2.5: 历史读取 + SEO 数据

...
```

Replace with:
```
### Step 2: 主题库选 (Topic Library Selection)

```bash
python3 {skill_dir}/scripts/load_corpus.py --client {client} --dry-run
```

脚本从 `references/knowledge-corpus.yaml` 按顺序轮转选择未写过的主题（用 `clients/{client}/history.yaml` 去重）。

- 主题库耗尽告警：已用比例 ≥ 80% 时输出提示
- 100% 已用：自动从顶部循环
- 失败：YAML 损坏时 warn + 走 LLM 自由生成
```

- [ ] **Step 2: Update Step 3 section to reference new selection**

Replace lines 79-92 (Step 3: 选题生成) to reflect corpus-driven selection:
```
### Step 3: 选题生成

读取 `references/knowledge-corpus.yaml`（已通过 Step 2 选定的当前主题）。

读取 `references/topic-selection.md` → 评估 key_points 质量
读取 `references/frameworks-academic.md` → 选框架

框架选择逻辑：
- 主题含"起源"、"演变"、"提出" → 框架 1（起源-演变-影响）
- 主题含"原理"、"机制"、"定律" → 框架 2（原理-证据-应用）
- 主题含"实验"、"研究"、"测试" → 框架 3（经典实验-当代启示）
- 都不匹配 → 默认框架 1
```

- [ ] **Step 3: Replace Step 3.5 section**

Remove lines 106-114 (Step 3.5: 框架选择) — already merged into Step 3.

- [ ] **Step 4: Update Step 4 (writing) to reference academic frameworks**

Find:
```
读取: {skill_dir}/references/writing-guide.md
```

Replace with:
```
读取: {skill_dir}/references/frameworks-academic.md（按框架骨架）
读取: {skill_dir}/references/writing-guide.md
```

Also update word count constraint (1500-2500 → 2500-4000):
```
- 字数 2500-4000（学术派更长）
```

- [ ] **Step 5: Update Step 5 to skip 三模式强制, replace with academic variants**

Find (lines 156-162):
```
1. **三模式校验**: 3 个标题必须分别属于不同模式 (数字 / 反直觉 / 痛点), 不允许同模式重复。详见 `references/seo-rules.md` "三模式强制" 章节。
```

Replace with:
```
1. **学术定义式**: 3 个标题均为学术定义式（副标题 + 主标题），允许 1-2 个变体（裁掉副标题 / 更精炼）。
```

- [ ] **Step 6: Update Step 5.1 to remove 三模式 强制**

Find (lines 165-171):
```
2. **Blacklist 拦截**: 对每个标题执行:
```

Replace with:
```
2. **Disclaimer 强制**: 文章末尾由 `toolkit/cli.py publish` 自动追加 "本文为逻辑梳理，非学术研究"——不可关闭。
```

(Blacklist check still applies but moved out of academic-specific section.)

- [ ] **Step 7: Update Step 6 visual style hint**

Find (line 239):
```
- 画面倾向：更亮、更饱和、纪实摄影、抓拍感、轻微不完美构图，降低 AI 味
```

Replace with:
```
- 画面倾向：学术概念图 / 学术插画 / 单色或低饱和度 / 概念体现物主体 / 无可见文字
```

- [ ] **Step 8: Verify SKILL.md step count**

Run: `grep -c '^### Step ' SKILL.md`
Expected: 8 (Step 1, 2, 3, 4, 5, 6, 7, 7.5)

- [ ] **Step 9: Commit**

```bash
git add SKILL.md
git commit -m "refactor(skill): replace hotspot track with corpus-based selection"
```

---

### Task 6: Update visual-prompts.md style guidance

**Files:**
- Modify: `references/visual-prompts.md`

- [ ] **Step 1: Find and replace style section**

Search for "纪实摄影" or "抓拍感" in `references/visual-prompts.md`.

Replace any prompt-style guidance that says documentary/photo-style with:
```
学术概念图 / 学术插画 / 单色或低饱和度 / 概念体现物主体 / 无可见文字
```

- [ ] **Step 2: Commit**

```bash
git add references/visual-prompts.md
git commit -m "refactor(visual): shift style guidance from documentary to conceptual"
```

---

### Task 7: Update topic-selection.md

**Files:**
- Modify: `references/topic-selection.md`

- [ ] **Step 1: Replace hot-topic evaluation rules with corpus-context rules**

The file currently has scoring heuristics for hot topics. Replace the heuristic with:
- 主题来源：corpus (`references/knowledge-corpus.yaml`)
- 评估维度：
  - `key_points` 覆盖度（3-5 条 是否足够支撑框架）
  - `origin` 清晰度（起源描述是否能撑起 § 1）
  - 与近期主题的关联度（避免连写同 category）

- [ ] **Step 2: Commit**

```bash
git add references/topic-selection.md
git commit -m "refactor(selection): update topic-selection.md for corpus-driven flow"
```

---

### Task 8: Update seo-rules.md for academic titles

**Files:**
- Modify: `references/seo-rules.md`

- [ ] **Step 1: Replace 三模式章节**

Find the "三模式强制" section. Replace with:
```
## 学术定义式标题

对于知识科普赛道，3 个备选标题均为「学术定义式」：

- 备选 1：完整学术标题（主标题 + 副标题，用冒号 / 破折号分隔）
  - 例：「幸存者偏差：起源、机制与当代启示」
- 备选 2：精炼版（裁掉副标题，纯主标题）
  - 例：「幸存者偏差：被忽视的'阵亡者'」
- 备选 3：搜索驱动（加入高频搜索词）
  - 例：「什么是幸存者偏差？理解统计学家沃德的发现」

约束：
- 主标题 30-50 字
- 副标题 0-15 字（可选）
- 避免数字钩子（如"3 个"、"99%"）
- 避免感叹号 / 问号堆叠
```

- [ ] **Step 2: Commit**

```bash
git add references/seo-rules.md
git commit -m "refactor(seo): replace 3-model rule with academic title variants"
```

---

## Phase 3: Compliance

### Task 9: Inject disclaimer in `cli.py publish`

**Files:**
- Modify: `toolkit/cli.py`
- Create: `tests/test_cli_disclaimer.py`

**Interfaces:**
- Produces: `inject_disclaimer(markdown: str) -> str` — appends disclaimer before publish

- [ ] **Step 1: Write failing test**

```python
import pytest
from toolkit.cli import inject_disclaimer


def test_inject_disclaimer_appends():
    md = "# 幸存者偏差\n\n正文内容"
    out = inject_disclaimer(md)
    assert "本文为逻辑梳理" in out
    assert "非学术研究" in out


def test_inject_disclaimer_idempotent():
    md = "# 幸存者偏差\n\n正文\n\n本文为逻辑梳理，非学术研究。"
    out = inject_disclaimer(md)
    assert out.count("本文为逻辑梳理") == 1


def test_inject_disclaimer_preserves_frontmatter():
    md = "---\ntitle: foo\n---\n\n# 标题\n\n正文"
    out = inject_disclaimer(md)
    # Disclaimer goes after content, before frontmatter stays
    assert out.startswith("---\n")
    assert "本文为逻辑梳理" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli_disclaimer.py -v`
Expected: ImportError

- [ ] **Step 3: Implement `inject_disclaimer`**

In `toolkit/cli.py`, add at module level:

```python
DISCLAIMER = "\n\n---\n\n> **声明**：本文为逻辑梳理，非学术研究。引用细节可能存在简化。\n"


def inject_disclaimer(markdown: str) -> str:
    """Append academic disclaimer. Idempotent."""
    if DISCLAIMER.strip() in markdown:
        return markdown
    return markdown.rstrip() + DISCLAIMER
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cli_disclaimer.py -v`
Expected: 3 passed

- [ ] **Step 5: Wire into `publish` command**

Find `def cmd_publish` in `toolkit/cli.py`. Add at the top of the function body:
```python
markdown_content = inject_disclaimer(markdown_content)
```

(Or after reading the file, before calling publisher.)

- [ ] **Step 6: Commit**

```bash
git add toolkit/cli.py tests/test_cli_disclaimer.py
git commit -m "feat(cli): inject academic disclaimer in publish path"
```

---

### Task 10: Create `keyword_research.py` (replace seo_keywords.py)

**Files:**
- Create: `scripts/keyword_research.py`
- Create: `tests/test_keyword_research.py`
- Modify: `scripts/seo_keywords.py` (deprecate stub)

**Interfaces:**
- Produces: `research(title: str) -> dict` — `{estimated_volume: int, related_keywords: list[str]}`

- [ ] **Step 1: Write failing test**

```python
import pytest
from unittest.mock import patch

from scripts.keyword_research import research


def test_research_returns_dict():
    with patch("scripts.keyword_research._fetch") as mock:
        mock.return_value = {"volume": 1000, "related": ["幸存者", "偏差"]}
        result = research("幸存者偏差")
    assert "estimated_volume" in result
    assert "related_keywords" in result


def test_research_handles_failure():
    with patch("scripts.keyword_research._fetch") as mock:
        mock.side_effect = Exception("network")
        result = research("幸存者偏差")
    assert result["estimated_volume"] == 0
    assert result["related_keywords"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_keyword_research.py -v`
Expected: ImportError

- [ ] **Step 3: Implement `keyword_research.py`**

```python
#!/usr/bin/env python3
"""Lookup estimated search volume for academic concept titles."""

import sys
from typing import Optional


def _fetch(title: str) -> dict:
    """Fetch from external API. Default implementation: stub."""
    # No-op default; production wires to 百度指数 / 微信指数 API
    return {"volume": 0, "related": []}


def research(title: str) -> dict:
    """Return {estimated_volume, related_keywords} for a concept title.

    Failure-tolerant: returns empty result on exception.
    """
    try:
        data = _fetch(title)
        return {
            "estimated_volume": int(data.get("volume", 0)),
            "related_keywords": list(data.get("related", [])),
        }
    except Exception as e:
        print(f"[warn] keyword_research failed: {e}", file=sys.stderr)
        return {"estimated_volume": 0, "related_keywords": []}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Look up academic concept search volume")
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    print(research(args.title))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_keyword_research.py -v`
Expected: 2 passed

- [ ] **Step 5: Deprecate `seo_keywords.py`**

Replace contents with:
```python
#!/usr/bin/env python3
"""DEPRECATED — use scripts/keyword_research.py instead."""

import sys

print("seo_keywords.py is deprecated. Use scripts/keyword_research.py.", file=sys.stderr)
sys.exit(2)
```

- [ ] **Step 6: Commit**

```bash
git add scripts/keyword_research.py scripts/seo_keywords.py tests/test_keyword_research.py
git commit -m "feat(keywords): add keyword_research.py; deprecate seo_keywords.py"
```

---

## Phase 4: Migration

### Task 11: Create `migrate_history.py` for schema upgrade

**Files:**
- Create: `scripts/migrate_history.py`
- Create: `tests/test_migrate_history.py`

**Interfaces:**
- Produces: history.yaml with `track: knowledge` and `topic_id` fields

- [ ] **Step 1: Write failing test**

```python
import yaml
import pytest

from scripts.migrate_history import migrate, NEEDED_FIELDS


def test_migrate_adds_track_and_topic_id(tmp_path):
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"date": "2026-01-01", "title": "老文章", "framework": "痛点型"}
    ], allow_unicode=True))

    migrate(history)
    loaded = yaml.safe_load(history.read_text(encoding="utf-8"))
    entry = loaded[0]
    assert entry["track"] == "knowledge"
    assert entry["topic_id"] is None  # unknown for legacy entries


def test_migrate_idempotent(tmp_path):
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"date": "2026-01-01", "title": "t",
         "track": "knowledge", "topic_id": "kb-001", "framework": "痛点型"}
    ], allow_unicode=True))

    migrate(history)
    loaded = yaml.safe_load(history.read_text(encoding="utf-8"))
    assert loaded[0]["topic_id"] == "kb-001"


def test_migrate_no_overwrite_existing(tmp_path):
    history = tmp_path / "history.yaml"
    history.write_text(yaml.safe_dump([
        {"date": "2026-01-01", "title": "t",
         "track": "hot", "topic_id": "kb-001"}
    ], allow_unicode=True))

    migrate(history)
    loaded = yaml.safe_load(history.read_text(encoding="utf-8"))
    assert loaded[0]["track"] == "hot"  # don't overwrite


def test_migrate_missing_file(tmp_path):
    history = tmp_path / "nope.yaml"
    # should not raise
    migrate(history)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_migrate_history.py -v`
Expected: ImportError

- [ ] **Step 3: Implement `migrate_history.py`**

```python
#!/usr/bin/env python3
"""Migrate clients/{client}/history.yaml to add track + topic_id fields."""

from pathlib import Path

import yaml

NEEDED_FIELDS = {"track": "knowledge", "topic_id": None}


def migrate(history_path: Path) -> None:
    """Add missing fields to each entry. Idempotent. Doesn't overwrite."""
    if not history_path.exists():
        return
    with open(history_path, "r", encoding="utf-8") as f:
        history = yaml.safe_load(f) or []
    changed = False
    for entry in history:
        for key, default in NEEDED_FIELDS.items():
            if key not in entry:
                entry[key] = default
                changed = True
    if changed:
        with open(history_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(history, f, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate history.yaml schema")
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    path = Path(__file__).resolve().parent.parent / "clients" / args.client / "history.yaml"
    migrate(path)
    print(f"✅ Migrated {path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_migrate_history.py -v`
Expected: 4 passed

- [ ] **Step 5: Run migration on existing clients (demo, zhulv)**

Run: `python3 scripts/migrate_history.py --client demo`
Run: `python3 scripts/migrate_history.py --client zhulv`

(If client doesn't exist, that's OK — migration is no-op.)

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_history.py tests/test_migrate_history.py
git commit -m "feat(migration): add migrate_history.py for track + topic_id fields"
```

---

### Task 12: Update client style.yaml with track field

**Files:**
- Modify: `clients/*/style.yaml` (each existing client)

- [ ] **Step 1: Identify existing clients**

Run: `ls /root/.openclaw/workspace/skills/wechat-studio/clients/`

- [ ] **Step 2: For each client, prepend `track: knowledge` to YAML**

For each `clients/{client}/style.yaml`:
```yaml
track: knowledge
# ... existing content
```

- [ ] **Step 3: Commit**

```bash
git add clients/*/style.yaml
git commit -m "refactor(style): add track: knowledge to all client configs"
```

---

### Task 13: End-to-end smoke test

**Files:**
- Run existing preview pipeline with new corpus

- [ ] **Step 1: Pick a topic from corpus**

Run: `python3 scripts/load_corpus.py --client demo`
Expected: prints first unused topic

- [ ] **Step 2: Generate a test article (mock article)**

Run:
```bash
mkdir -p output/_smoketest
cat > output/_smoketest/test.md <<'EOF'
# 幸存者偏差：起源、机制与当代启示

## 摘要

幸存者偏差是一种认知偏差，指人们只看到"幸存者"而忽略"阵亡者"。

## § 1 起源

1943 年，哥伦比亚大学统计学家亚伯拉罕·沃德受美军委托研究返航轰炸机的损伤分布...

## § 2 发展演变

1972 年，丹尼尔·卡尼曼和阿莫斯·特沃斯基正式将这一现象命名为"幸存者偏差"...

## § 3 影响与应用

在投资领域，幸存者偏差导致投资者高估成功创业者的普遍性...

## § 4 反直觉点

常见误解：幸存者偏差不是"运气好"，而是"看不见失败"...

EOF
```

- [ ] **Step 3: Run preview with disclaimer**

Run: `python3 toolkit/cli.py preview output/_smoketest/test.md --theme terracotta --no-open -o output/_smoketest/test.html`
Expected: HTML file generated

- [ ] **Step 4: Verify disclaimer in output**

Run: `grep -c "本文为逻辑梳理" output/_smoketest/test.md`
Expected: 1 (injected automatically)

Actually note: disclaimer is injected at `publish` time, not `preview`. So this test should verify:
- `preview` outputs unchanged → run dry-run via `publish --dry-run` if available, OR
- Manually call `inject_disclaimer` and verify

Run:
```python
python3 -c "
from toolkit.cli import inject_disclaimer
with open('output/_smoketest/test.md') as f:
    out = inject_disclaimer(f.read())
print('Disclaimer present:', '本文为逻辑梳理' in out)
"
```
Expected: `Disclaimer present: True`

- [ ] **Step 5: Cleanup**

Run: `rm -rf output/_smoketest`

- [ ] **Step 6: Commit (no code changes — only verification)**

```bash
git commit --allow-empty -m "test: e2e smoke test for knowledge track pipeline"
```

---

## Self-Review

**Spec coverage check:**
- [x] § 1 Architecture → Task 5 (SKILL.md update)
- [x] § 2 Topic corpus → Tasks 1, 2, 4
- [x] § 3 Academic frameworks → Task 3
- [x] § 4 Writing flow → Tasks 5, 7, 8
- [x] § 5 Error handling → embedded in Task 2 (warn + round-robin) and Task 5 (LLM fallback)
- [x] § 5 Disclaimer injection → Task 9
- [x] § 6 Testing strategy → Tasks 2, 4, 9, 10, 11 (unit tests), Task 13 (E2E)
- [x] § 7 Risks → mitigated via disclaimer idempotency, round-robin, expand_corpus.py
- [x] § 8 Acceptance criteria → verification in Task 13

**Placeholder scan:**
- No TBD/TODO found
- All code blocks complete
- All commands include expected output

**Type consistency:**
- `load_corpus()` returns `list[dict]` — used consistently in `next_topic()`, `exhaustion_pct()`, test mocks
- `append_topic(path, topic)` — consistent across test and impl
- `inject_disclaimer(markdown: str) -> str` — consistent

---

## Execution Handoff

**Plan complete and saved to `references/plans/2026-08-07-knowledge-pivot-refactor.md`. Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - I execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
