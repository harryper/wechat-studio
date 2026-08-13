# WeChat Studio

公众号 AI 内容工作台：从知识库选题、长文写作和配图，到主题预览和微信草稿箱。

## 快速开始

```bash
git clone --depth 1 https://github.com/harryper/wechat-studio.git ~/.openclaw/skills/wechat-studio
cd ~/.openclaw/skills/wechat-studio
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

可以通过两种入口使用：

- OpenClaw：说“写一篇公众号文章”，由 `SKILL.md` 编排流程。
- Web 工作台：运行 `docker compose up -d --build`，访问 `http://localhost:9997`。

## 实际主流程

OpenClaw 和 Web 工作台共用同一套内容契约：

```text
1. 从 references/knowledge-corpus.yaml 选题
2. 按标题关键词选择学术写作框架
3. 通过 Anthropic 兼容 API 生成 2500–4000 字 Markdown 长文
4. 后台生成封面 + 4 张内文图；单张失败时使用 PIL 占位图
5. 使用所选主题生成 HTML 预览，并保存预览历史
6. 在线编辑、换主题，或按文章/全部图片/单张图片重新生成
7. 通过发布前检查后，由用户确认创建微信草稿
```

发布时会自动：

- 从 H1 提取微信标题；
- 从正文移除 H1、内部分类元数据和封面图；
- 识别名为 `cover.jpg/png/webp/gif` 的图片作为微信封面；
- 追加“本文为逻辑梳理，非学术研究”声明。

Web 工作台已支持可选客户 Style/Playbook、标题 Blacklist 和 AI 痕迹检测。热点抓取、SEO 备选标题、人工改稿学习和数据复盘仍是 Agent/CLI 的可选扩展能力。

### Web 产品化能力

- 生成请求返回 `job_id`，前端轮询写作、配图、排版和质量检查进度。
- 任务状态保存在 `webapp/_data/jobs/`，页面刷新后可恢复轮询。
- 历史文章可在线修改 Markdown，保存后立即重新排版。
- 可只重写文章、重生全部图片、重生指定图片或单独换主题。
- 发布前检查标题、图片完整性、封面、Blacklist、占位图和 AI 痕迹分。

## 配置

```bash
# 文章生成（Web 生成预览必需）
export ANTHROPIC_BASE_URL="https://your-endpoint.example"
export ANTHROPIC_AUTH_TOKEN="your-token"
export ANTHROPIC_MODEL="MiniMax-M3"

# 微信草稿发布时必需
export WECHAT_APPID="wx_your_appid"
export WECHAT_SECRET="your_appsecret"

# 可选生图供应商；都未配置时 Web 使用本地占位图
export MINIMAX_API_KEY="your-minimax-key"
export OPENAI_API_KEY="sk-..."
export DOUBAO_API_KEY="your-volc-key"

# Web 登录；部署时请务必替换默认值
export APP_PASSWORD="a-strong-password"
export APP_COOKIE_SECRET="a-long-random-secret"
```

`config.yaml` 支持 `${VAR}` 和 `${VAR:-default}` 占位符，不要在仓库中写入明文密钥。

## 主题与排版

项目内置 38 套主题。可用的 xiaohu 主题走外部 `xiaohu-wechat-format` 引擎，其余主题走项目原生转换器。

```bash
python3 toolkit/cli.py themes
python3 toolkit/cli.py gallery article.md --no-open -o theme-gallery.html
python3 toolkit/cli.py preview article.md --theme terracotta --no-open
python3 toolkit/cli.py publish article.md --cover cover.png --title "标题"
```

`xiaohu-wechat-format` 当前是兄弟目录依赖；Docker Compose 默认将宿主机的 `/root/.openclaw/workspace/skills/xiaohu-wechat-format` 挂载到容器。

## 可选扩展

```bash
python3 scripts/fetch_hotspots.py --limit 20
python3 scripts/humanness_score.py article.md --verbose
python3 scripts/fetch_stats.py --client CLIENT --days 7
python3 scripts/learn_edits.py --client CLIENT --draft draft.md --final final.md
```

## 目录

```text
wechat-studio/
├── SKILL.md                 # OpenClaw 编排指令
├── webapp/                  # Flask Web 工作台和预览历史
├── toolkit/                 # 排版、生图、微信 API 和发布 CLI
├── scripts/                 # 写作、选题、检测和学习工具
├── references/              # 知识库与按需加载的写作规范
├── toolkit/themes/          # 38 套主题 YAML
├── clients/                 # 本地客户配置，不进 Git
└── dist/openclaw/           # scripts/build_openclaw.py 生成的分发包
```

## 验证

```bash
python3 -m pytest -q
python3 -m compileall -q toolkit scripts webapp
python3 scripts/diagnose.py --json
```

MIT · https://github.com/harryper/wechat-studio
