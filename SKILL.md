---
name: wechat-studio
description: >-
  生成、配图、排版、预览并发布微信公众号文章，也支持热点抓取、客户风格学习、文章质量检测和发布数据复盘。
  用于用户明确提到公众号、微信文章、微信排版、微信草稿箱、封面图或公众号选题的任务；不用于没有微信上下文的通用文章、邮件、PPT 或短视频任务。
---

# WeChat Studio

按“选题 → 框架写作 → 配图 → 主题预览 → 用户确认 → 微信草稿”执行。默认先交付可检查的预览；只有用户明确要求发布，或在看过预览后确认，才推送微信草稿箱。

## 主流程

### 1. 确定选题

- 用户给出明确选题时，直接使用。
- 用户未给出选题时，从 `references/knowledge-corpus.yaml` 选择。
- 给出客户名时，优先运行 `python3 {skill_dir}/scripts/load_corpus.py --client {client} --dry-run`，使用 `clients/{client}/history.yaml` 去重。

客户配置存在时读取 `clients/{client}/style.yaml`；不存在时可用 `style.example.yaml` 创建，但不得阻断通用知识库流程。

### 2. 选择框架

读取 `references/frameworks-academic.md`，按以下规则选择：

- 起源、演变、提出、诞生：起源—演变—影响。
- 原理、机制、定律、法则：原理—证据—应用。
- 实验、研究、测试：经典实验—当代启示。
- 都不匹配：起源—演变—影响。

### 3. 生成文章

读取 `references/writing-guide.md`。如果客户存在 `playbook.md`，客户规则优先于通用规则。

输出必须满足：

- Markdown 以单个 H1 标题开头，正文 2500–4000 个中文字。
- H1 之后可放分类和主题 ID 元数据；发布时会移除。
- 使用 H2 组织摘要和 4 个主要章节。
- 引用人物、年份和研究时不编造精确数据。
- 不手工写声明；`toolkit/cli.py publish` 会幂等追加。

对知识库主题运行：

```bash
python3 {skill_dir}/scripts/write_article.py --topic {topic_id} --out {markdown_path}
```

该命令需要 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 和可选的 `ANTHROPIC_MODEL`。

### 4. 配图

读取 `references/visual-prompts.md`。客户存在 `gpt-image-2-prompts.md` 时将其作为覆盖层。默认生成 5 张图：

- `images/cover.jpg`：封面；
- `images/inline-1.jpg`：前半部论点配图；
- `images/inline-2.jpg`：核心机制配图；
- `images/inline-3.jpg`：证据/实验配图；
- `images/inline-4.jpg`：应用/边界配图。

使用 `toolkit/image_gen.py` 中的供应商链。MiniMax API 成功返回的图片全部保留为真实图片，仅在供应商异常时由 Web 工作台回退到 PIL 占位图以保持预览可用；Agent 直接流程保留成功图片并说明失败项。不得把占位图当作真实 AI 图片汇报。

提示词必须是纯视觉描述：不要用书名号引用标题，也不要出现学术插画 / 编辑插画 / 概念图 / 机制图 / 线稿说明图 / 流程图 / 信息图等天然诱导文字或版面文字的构图词。每条提示词统一追加电影感场景约束：单一视觉焦点、主体正在完成一个具体动作，并禁止出现标题、段落、字母、汉字、数字、水印、logo、箭头、路线、流程节点、标签、图例、表格、图表、书页、文件、标牌、屏幕、设备界面或海报布局。

质量控制由人工完成：用户在 Web 工作台预览时检查每张配图，发现伪文字或构图不满意时使用"重生指定图片"重新生成对应的单张图。

供应商条目支持 `enabled` 开关；仓库默认 `enabled: "${OPENAI_IMAGE_ENABLED:-false}"` 关闭 OpenAI 图片供应商，不显式 `export OPENAI_IMAGE_ENABLED=true` 就不会产生 OpenAI 费用。

### 5. 预览

```bash
python3 {skill_dir}/toolkit/cli.py preview {markdown_path} \
  --theme {theme} --no-open -o {html_path}
```

- xiaohu 主题走兄弟项目 `xiaohu-wechat-format`，其余主题走项目原生转换器。
- Web 工作台将 HTML/图片运行产物存入 `webapp/_data/workdirs/`；选题、正文、历史、任务、发布记录和状态事件统一保存到 Cloudflare D1。
- 生成预览后先让用户检查标题、正文、配图和主题。

### 6. 发布草稿

用户明确要求推送时运行：

```bash
python3 {skill_dir}/toolkit/cli.py publish {markdown_path} \
  --theme {theme} --cover {cover_path} --title "{title}"
```

`--cover` 可省略；发布器会自动识别路径中名为 `cover.jpg/jpeg/png/gif/webp` 的图片。发布器会：

1. 从完整 Markdown 提取 H1、摘要和图片列表。
2. 从微信正文移除 H1、分类元数据和封面图。
3. 上传内文图并替换 HTML 路径。
4. 上传封面并创建微信草稿。

发布失败时保留 Markdown、图片和本地 HTML，返回错误与文件路径。

## Web 工作台边界

Web 页面将 LLM 长文写作、5 张图和排版作为后台任务执行，通过 `job_id` 轮询进度。任务完成后支持在线编辑 Markdown、换主题、只重写文章、重生全部图片或指定图片。

Web 可选加载客户 Style/Playbook，并在生成后及发布前检查标题 Blacklist、AI 痕迹分、标题长度、图片完整性、封面和占位图。Blacklist 或必需文件检查失败时不得发布。

Web 不会自动执行热点抓取、SEO 备选标题、人工改稿学习或数据复盘。

## 可选扩展

- 热点候选：`python3 {skill_dir}/scripts/fetch_hotspots.py --limit 20`
- 标题 Blacklist：`python3 {skill_dir}/scripts/check_blacklist.py "{title}" --client {client}`
- 文章质量检测：`python3 {skill_dir}/scripts/humanness_score.py {markdown_path} --verbose`
- SEO 辅助：按需读取 `references/seo-rules.md`。
- 效果复盘：`python3 {skill_dir}/scripts/fetch_stats.py --client {client} --days 7`
- 学习改稿：`python3 {skill_dir}/scripts/learn_edits.py --client {client} --draft {draft} --final {final}`
- 建立 Playbook：`python3 {skill_dir}/scripts/build_playbook.py --client {client}`
- 学习排版主题：`python3 {skill_dir}/toolkit/cli.py learn-theme {wechat_url} --name {theme_name}`

## 错误处理

| 阶段 | 处理 |
|---|---|
| 知识库损坏或主题缺失 | 请用户给出选题，或明确说明自由选题 |
| LLM 未配置或调用失败 | 停止写作并返回具体配置/API 错误 |
| 单张 AI 图片失败 | Web 使用占位图；Agent 保留成功图并报告失败图 |
| 排版失败 | 保留 Markdown 和图片，返回错误 |
| 微信发布失败 | 保留本地 HTML，返回 API 错误 |

## 回复要求

说明最终标题、主题、产物路径、图片是真实 AI 图还是占位图。如果已推送，返回 `media_id` 并提醒到公众号后台检查；如果未推送，明确说明等待用户确认。
