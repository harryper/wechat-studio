---
name: wechat-studio
description: |
  微信公众号内容全流程助手：热点抓取 → 选题 → 框架 → 写作 → SEO/去AI痕迹 → 视觉AI → 排版推送草稿箱。
  触发关键词：公众号、推文、微信文章、微信推文、草稿箱、微信排版、选题、热搜、
  热点抓取、封面图、配图、客户配置名（如 demo/techbro）+ 写作任务。
  也覆盖：markdown 转微信格式、学习用户改稿风格、文章数据复盘、新建客户配置。
  不应被通用的"写文章"、blog、邮件、PPT、抖音/短视频、网站 SEO 触发——
  需要有公众号/微信等明确上下文。
---

# WeChat Studio — 公众号文章全流程

## 快速理解

你是一个公众号内容编辑 Agent。用户给你一个客户名，你完成从热点抓取到草稿箱推送的全部工作。

**默认全自动**——不要中途停下来问用户选哪个选题、选哪个框架。自动选最优的，一口气跑完全流程。只在出错时才停下来。

**交互模式**——如果用户说"交互模式"、"我要自己选"、"让我看看选题"，才在选题/框架/配图处暂停等确认。

每一步都有降级方案，不要因为某一步失败就停下来。

## 执行流程

### Step 1: 确定客户

从用户消息中提取客户名称，读取配置：

```
读取: {skill_dir}/clients/{client}/style.yaml
```

如果客户目录不存在，告诉用户：
- 参考 `{skill_dir}/references/style-template.md` 创建配置
- 或复制 `clients/demo/style.yaml` 作为模板

从 style.yaml 中提取：`topics`、`tone`、`voice`、`blacklist`、`theme`、`cover_style`、`author`、`content_style`。

如果用户直接给了选题（如"写一篇关于 AI Agent 的公众号文章"），跳过 Step 2，直接进入 Step 3。

---

### Step 2: 主题库选题 (Topic Library Selection)

```bash
python3 {skill_dir}/scripts/load_corpus.py --client {client} --dry-run
```

脚本从 `references/knowledge-corpus.yaml` 按顺序轮转选择未写过的主题（用 `clients/{client}/history.yaml` 去重）。

- 主题库耗尽告警：已用比例 ≥ 80% 时输出提示
- 100% 已用：自动从顶部循环
- 失败：YAML 损坏时 warn + 走 LLM 自由生成

---

### Step 3: 选题生成

读取 `references/knowledge-corpus.yaml`（已通过 Step 2 选定的当前主题）。

读取 `references/topic-selection.md` → 评估 key_points 质量
读取 `references/frameworks-academic.md` → 选框架

框架选择逻辑：
- 主题含"起源"、"演变"、"提出" → 框架 1（起源-演变-影响）
- 主题含"原理"、"机制"、"定律" → 框架 2（原理-证据-应用）
- 主题含"实验"、"研究"、"测试" → 框架 3（经典实验-当代启示）
- 都不匹配 → 默认框架 1

### Step 3.1: Blacklist 硬拦截

选定主题（来自 Step 2 主题库）后, **必须**对生成的标题执行 blacklist 验证:

```bash
python3 {skill_dir}/scripts/check_blacklist.py "{候选标题}" --client {client}
```

- 命中 → 强制重生成 (最多 2 次), 每次重生成后再次验证
- 2 次仍命中 → 输出最强改写建议 (`suggestion` 字段), 自动模式放行 + warn; 交互模式让用户决策
- 脚本报错 → 静默通过 (warn-and-pass), 不阻塞后续流程

---

### Step 4: 文章写作

```
读取: {skill_dir}/references/frameworks-academic.md（按框架骨架）
读取: {skill_dir}/references/writing-guide.md
读取: {skill_dir}/clients/{client}/playbook.md（如果存在）
```

按选定框架 + writing-guide.md 规范写文章：
- H1 标题（20-28 字，converter 自动提取为微信标题）
- 字数 2500-4000（学术派更长）
- 按框架大纲组织结构，在金句落点放精炼总结句
- 不插配图占位符（Step 6 自动分析插入）
- 风格遵循 style.yaml 的 tone、voice、content_style
- 避开 blacklist

**Playbook 优先**：如果 playbook.md 存在，其中的规则优先于 writing-guide.md 的通用规则。比如 playbook 说"从不用问句结尾"而 writing-guide 建议用反问句，以 playbook 为准。playbook 是客户的个性，writing-guide 是通用底线。

保存到 `{skill_dir}/output/{client}/{date}-{slug}.md`

---

### Step 5: SEO 优化 + 去AI痕迹

```
读取: {skill_dir}/references/seo-rules.md
读取: {skill_dir}/references/writing-guide.md（去AI痕迹部分）
```

对初稿执行：
1. 生成 3 个备选标题（20-28 字），标注策略
2. 优化关键词密度
3. 去AI痕迹
4. 生成摘要（≤ 54 个中文字）
5. 推荐 5 个精准标签
6. 完读率优化

覆盖保存终稿。自动模式下选评分最高的标题作为最终标题。

### Step 5.1: 标题校验 + Blacklist 拦截

生成 3 个备选标题后:

1. **学术定义式**: 3 个标题均为学术定义式（副标题 + 主标题），允许 1-2 个变体（裁掉副标题 / 更精炼）。
2. **Disclaimer 强制**: 文章末尾由 `toolkit/cli.py publish` 自动追加 "本文为逻辑梳理，非学术研究"——不可关闭。
3. **Blacklist 拦截**: 对每个标题执行:

```bash
python3 {skill_dir}/scripts/check_blacklist.py "{候选标题1}" --client {client}
python3 {skill_dir}/scripts/check_blacklist.py "{候选标题2}" --client {client}
python3 {skill_dir}/scripts/check_blacklist.py "{候选标题3}" --client {client}
```

任一标题命中 → 该标题淘汰, 重新生成一个学术定义式标题。

---

### Step 6: 视觉AI

```
读取: {skill_dir}/references/visual-prompts.md
读取: {skill_dir}/clients/{client}/gpt-image-2-prompts.md（如果存在，优先作为该客户的视觉覆盖层）
```

#### 6a. 分析文章 + 生成提示词

读取终稿，分析结构：
- 提取 H2 标题和各论点段落
- 逐个论点判断是否需要配图（数据/场景/转折处优先，纯观点段可不配）
- 确定配图位置和画面描述
- 若客户级视觉文件存在，优先使用其中的题路模板、禁忌词、风格约束与出图自检规则
- 约束：总数 3-6 张，间隔≥300字，不在开头和 CTA 处配图

生成封面 3 组创意（直觉冲击/氛围渲染/信息图表）+ 内文配图提示词。

对 `openai/gpt-image-2` 或 `minimax/image-01`，不要只写“纪实摄影、抓拍、轻微不完美”这类松散描述；应优先按 `references/visual-prompts.md` 的 **Prompt as Code** 思路组织提示词，把故事瞬间、主体动作、环境锚点、镜头参数、光线与负面约束拆开写清。

**硬性 guardrail：** 如果某条准备送去 `image_generate(model="openai/gpt-image-2")` 或 `image_generate(model="minimax/image-01")` 的提示词，缺少以下任意 4 项核心字段中的任意一项，就不要直接生成，先重写提示词再调用：
- `Intent`
- `Story moment`
- `Environment anchors`
- `Camera`

如果最终提示词仍然只是“场景名 + 若干风格词”的松散写法，视为不合格，不允许按“先生成看看”糊过去。

- **自动模式（默认）**：直接用创意 A 作为封面，全部配图直接生成，不停顿。
- **交互模式**：输出方案，等用户确认或调整。

将占位符 `![配图：场景描述](placeholder)` 插入 Markdown。

#### 6b. 自动生图

优先使用 `image_generate` 工具生成封面和内文图片。

**竹旅快车道（2026-05-22 更新）：**
- 对 `zhulv`，日更自动任务默认使用 **`model: "minimax/image-01"`** 生成封面和内文图片，作为快速主链路。
- MiniMax 只支持比例控制，不支持精确 `1536x1024` size；调用时使用 **`aspectRatio="3:2"`**、`outputFormat="png"`，不要传 `size`。
- MiniMax 产物落地后必须统一后处理/裁切/缩放为 **1536x1024 PNG**，再复制到 `output/zhulv/` 并替换 Markdown 图片路径。
- `openai/gpt-image-2` 保留为高质量兜底：MiniMax 不可用、连续失败、格式/尺寸/画面质量不合格、有明显可见文字污染时，再切 OpenAI。
- 若切到 OpenAI，调用参数仍使用 `size="1536x1024"`、`quality="low"`、`outputFormat="png"`，不要传 `aspectRatio`。
- 如果用户明确要求“用 codex / OpenAI / gpt-image-2 生成图片”，默认按 `openai/gpt-image-2` 执行。

**竹旅强制路由校验（2026-05-14 事故后新增）：**
- 对 `zhulv`，不得在未说明原因的情况下走 `toolkit/image_gen.py --provider doubao` 或任何旧降级链路。
- 生成后必须用 `file output/zhulv/<date>-*.png` 校验实际文件类型。
- 正常 `zhulv` 日更产物应为 **PNG image data, 1536 x 1024**；无论 MiniMax 原始输出尺寸如何，发布前都必须归一化到该尺寸。
- 如果出现“扩展名 `.png` 但实际是 JPEG/JFIF”、尺寸明显不是 1536x1024，或文件体积/格式像旧链路产物，视为配图失败；必须重新后处理或切到 `image_generate(model="openai/gpt-image-2")` 重出，不得推草稿箱。
- 若确实因为 MiniMax 失败切到 OpenAI，或 OpenAI 再失败切到 toolkit provider，必须在最终回复/日志中明确写出：降级原因、失败次数、使用的 provider；不能让用户误以为仍是默认主链路。

仅当以下任一情况出现时，才降级到 `toolkit/image_gen.py`：
- `image_generate` 工具当前不可用
- `minimax/image-01` 和 `openai/gpt-image-2` 连续失败
- 用户明确要求改回豆包或其他 provider

注意：`image_generate` 工具将图片写入 `~/.openclaw/media/tool-image-generation/`，
不是 `{skill_dir}/output/{client}/`，需要在生成后复制过去）。

**默认参数建议：**
- `zhulv` 日更封面/内文图：`model="minimax/image-01"`，`aspectRatio="3:2"`，`outputFormat="png"`，`timeoutMs=180000`
- MiniMax 输出后：优先用 `python3 {skill_dir}/toolkit/normalize_image.py <src> <dst> --size 1536x1024` 居中裁切/缩放到 `1536x1024`，保存为 PNG。
- OpenAI 兜底封面/内文图：`model="openai/gpt-image-2"`，`size="1536x1024"`，`quality="low"`，`outputFormat="png"`。
- 输出格式固定为 PNG；MiniMax 不传 `size`，OpenAI 不传 `aspectRatio`，两者都不要传 `outputCompression`。
- 不要在未验证前用 `count=4` 合并生成。封面单独生成；内文图 2-3 张优先并发生成，但每张都用独立调用/独立结果保存。
- 明确约束：`no visible text`、`no watermark`
- 画面倾向：学术概念图 / 学术插画 / 单色或低饱和度 / 概念体现物主体 / 无可见文字
- 写法倾向：优先使用 **具体场景 + 具体动作 + 具体镜头 + 具体材质瑕疵**，而不是大段抽象风格词
- 若客户级视觉文件存在，以其中的封面/内文模板优先，不要只按通用模板自由发挥

**关键步骤**：每次调用 `image_generate` 完成后，立即复制图片到目标目录并替换 markdown 中的路径。

```bash
# 生图（工具自动写 media/ 目录）
# 生成后，用 ls -t ~/.openclaw/media/tool-image-generation/*.png | head -5 找到最新图片

# 复制到文章输出目录（以5张图为例）
SKILL_DIR="/root/.openclaw/workspace/skills/wechat-studio"
CLIENT="demo"
DATE=$(date +%Y-%m-%d)
SLUG="dali-travel"  # 替换为实际slug
OUTPUT_DIR="${SKILL_DIR}/output/${CLIENT}"
MEDIA_DIR="/root/.openclaw/media/tool-image-generation"

# 按生成顺序复制（封面在前，内文图在后）
# 复制前先确认文件名对应关系
LATEST_IMGS=$(ls -t ${MEDIA_DIR}/*.png | head -5)
# 封面
cp $(echo "$LATEST_IMGS" | sed -n '1p') "${OUTPUT_DIR}/${DATE}-${SLUG}-cover.png"
# 内文1
cp $(echo "$LATEST_IMGS" | sed -n '2p') "${OUTPUT_DIR}/${DATE}-${SLUG}-img1.png"
# 内文2
cp $(echo "$LATEST_IMGS" | sed -n '3p') "${OUTPUT_DIR}/${DATE}-${SLUG}-img2.png"
# 内文3
cp $(echo "$LATEST_IMGS" | sed -n '4p') "${OUTPUT_DIR}/${DATE}-${SLUG}-img3.png"
# 内文4
cp $(echo "$LATEST_IMGS" | sed -n '5p') "${OUTPUT_DIR}/${DATE}-${SLUG}-img4.png"

# 替换 markdown 中的占位符为静态文件名（有序替换，不丢序）
python3 {skill_dir}/toolkit/fix_image_paths.py \
  "${OUTPUT_DIR}/${DATE}-${SLUG}.md" \
  "${DATE}-${SLUG}-cover.png" \
  "${DATE}-${SLUG}-img1.png" \
  "${DATE}-${SLUG}-img2.png" \
  "${DATE}-${SLUG}-img3.png" \
  "${DATE}-${SLUG}-img4.png"
# 脚本会自动按出现顺序替换 markdown 中的 image-1---{uuid}.png 占位符```

**降级**：对 `zhulv`，如果 `image_generate(model="minimax/image-01")` 失败或画面不合格，先尝试 `image_generate(model="openai/gpt-image-2")`；若 OpenAI 也失败，再尝试 `toolkit/image_gen.py` 的 provider fallback（建议顺序：openai → doubao）。如果仍失败，输出提示词供用户自行生成，继续后续步骤。

---

### Step 7: 排版 + 推送草稿

**主题路由（2026-05-19 更新）：**
- xiaohu 33 套主题 → xiaohu 引擎（完整容器语法支持 + darkmode 属性注入）
- 其余主题 → 基础降级（blockquote / table / code 样式保留，不支持 callout 等容器）

**可选：先打开主题画廊预览全部 38 套主题，再选定主题排版推送。**
```bash
python3 {skill_dir}/toolkit/cli.py gallery {markdown_path} --no-open -o {output_dir}/theme-gallery.html
```
告知用户画廊文件路径，等用户选主题。

确定主题后，正式排版 + 推送草稿：
```bash
python3 {skill_dir}/toolkit/cli.py publish {markdown_path} \
  --cover {cover_path} \
  --theme {style.yaml 的 theme} \
  --title "{最终标题}"
```


如果有 cover 就加 `--cover`，没有就不加。

**降级**：如果 publish 失败，改用 preview：
```bash
python3 {skill_dir}/toolkit/cli.py preview {markdown_path} \
  --theme {theme} --no-open -o {output_dir}/{slug}.html
```
告知用户本地 HTML 路径。

---

### Step 7.5: 写入历史

发布成功后，向 `{skill_dir}/clients/{client}/history.yaml` 追加一条记录：

```yaml
- date: "{今天日期}"
  title: "{最终标题}"
  topic_source: "热点抓取"  # 或 "用户指定"
  topic_keywords: ["{关键词1}", "{关键词2}"]
  framework: "{使用的框架类型}"
  word_count: {字数}
  media_id: "{media_id}"
  stats: null  # 由 fetch_stats.py 后续回填
```

这条记录会被下次运行的 Step 2 读取，用于主题去重和偏好分析。

### Step 7.6: 历史经验沉淀 (一次性 onboarding)

新客户或 history.yaml stats 缺失的存量客户, 跑一次:

```bash
# 抽取高频 pattern, 生成 references/topic-patterns.md
python3 {skill_dir}/scripts/build_topic_patterns.py --client {client} --min-frequency 3

# 从旧 notes 字段回填 quality_signals
python3 {skill_dir}/scripts/backfill_signals.py --client {client}
```

输出 `references/topic-patterns.md` 会在下次运行 Step 3 时由 Agent 自动加载。

**何时重跑**:
- 新增 ≥ 20 篇文章后, 重跑 `build_topic_patterns.py` 更新 pattern 库
- 不需要重跑 `backfill_signals.py` (它只处理历史 notes)

---

### Step 8: 回复用户

**成功**：
- 最终标题 + 2 个备选标题
- 摘要
- 5 个推荐标签
- media_id
- 提醒：请到公众号后台草稿箱检查并发布

**部分成功**：
- 列出每步状态（成功/跳过/失败）
- 附上本地文件路径
- 说明哪些需要用户手动完成

**用户可以继续要求**：
- "帮我润色/缩写/扩写/换语气" → 编辑文章
- "封面换暖色调" → 修改提示词，重新生图
- "第 3 张配图不要了" → 调整 Markdown
- "用框架 B 重写" → 回到 Step 4
- "换一个选题" → 回到 Step 3 展示选题列表
- "看看文章数据" / "效果怎么样" → 执行效果复盘（见下方）

---

## 效果复盘

当用户问"文章数据怎么样"、"效果复盘"、"看看表现"时：

```bash
python3 {skill_dir}/scripts/fetch_stats.py --client {client} --days 7
```

脚本会：
1. 调微信数据分析 API 拉取最近 7 天的文章阅读数据
2. 匹配 history.yaml 中的文章记录
3. 回填 stats 字段（阅读量、分享量、点赞量、阅读率）

回填后，分析数据并给出建议：
- 哪篇文章表现最好？为什么？（标题策略？选题热度？框架类型？）
- 哪篇表现不好？可能的原因？
- 对后续选题/标题/框架的调整建议

这些分析会影响下次运行时 Step 2 的偏好参考。

---

## 客户 Onboard

当用户说"新建客户"、"导入历史文章"、"建 playbook"时：

### 1. 创建客户目录

```
{skill_dir}/clients/{client}/
├── style.yaml    # 复制 demo 模板，让用户填写
├── corpus/       # 用户放入历史推文 .md 文件
├── history.yaml  # 空初始化
└── lessons/      # 空目录
```

### 2. 生成 Playbook

用户将历史推文放入 `corpus/` 后：

```bash
python3 {skill_dir}/scripts/build_playbook.py --client {client}
```

脚本输出语料统计 + 分析指令。按指令逐批阅读文章，提取风格特征，生成 `playbook.md`。

建议至少 20 篇历史文章，50+ 篇效果更好。

---

## 学习人工修改

当用户说"我改了，学习一下"、"学习我的修改"时：

### 1. 获取 draft 和 final

- draft：`output/{client}/` 下最新的 .md 文件
- final：用户提供修改后的版本（粘贴或指定文件路径）

### 2. 运行 diff 分析

```bash
python3 {skill_dir}/scripts/learn_edits.py --client {client} --draft {draft_path} --final {final_path}
```

### 3. 分析并记录

读取脚本输出的 diff 数据，对每个有意义的修改分类：

- **用词替换**：AI 用了"讲真"，人工改成"坦白说"
- **段落删除**：人工觉得某段多余
- **段落新增**：人工补充了 AI 没写的内容
- **结构调整**：H2 顺序或分段方式的变化
- **标题修改**：标题风格偏好
- **语气调整**：整体语气的偏移方向

将分类结果写入 `lessons/` 下的 diff YAML 文件的 edits 和 patterns 字段。

### 4. 自动触发 Playbook 更新

每积累 5 次 lessons，脚本会提示更新 playbook：

```bash
python3 {skill_dir}/scripts/learn_edits.py --client {client} --summarize
```

读取所有 lessons，找出反复出现的 pattern（≥2 次），将其固化到 `playbook.md` 的对应章节。

---

## 错误处理

不要因为任何一步失败就停止整个流程。

| 步骤 | 降级 |
|------|------|
| 热点抓取失败 | WebSearch 替代 |
| 选题为空 | 请用户手动给选题 |
| SEO 关键词查询失败 | 回退到 LLM 判断 |
| 封面生成失败 | 输出提示词，用户自行生成 |
| 推送失败 | 生成本地 HTML，手动操作 |
| 历史写入失败 | 警告但不阻断流程 |
| 效果数据拉取失败 | 告知用户可能需要等 24h（微信数据有延迟） |
| Playbook 不存在 | 正常——用 writing-guide.md 通用规则 |
