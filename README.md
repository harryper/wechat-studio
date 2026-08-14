# WeChat Studio

公众号 AI 内容工作台：从知识库选题、长文写作和配图，到主题预览、在线修改和微信草稿箱发布。

当前版本：`1.5.0`

## 功能概览

- 从 `references/knowledge-corpus.yaml` 选择选题，并按关键词匹配写作框架。
- 通过 Anthropic Messages 兼容接口生成 2500–4000 字 Markdown 长文。
- 异步生成 1 张封面和 4 张内文图；单张失败时生成本地占位图，不中断整篇任务。
- 提供 38 套主题、桌面/移动预览、Markdown 在线修改和 D1 内容历史。
- 选题中心支持搜索、状态/来源/分类筛选和自定义主题。
- 支持重写文章、重生全部图片、重生单张图片及单独换主题。
- 发布前检查标题、图片、封面、客户 Blacklist、占位图和 AI 痕迹分。
- 经用户确认后创建微信公众号草稿，不会自动群发。

## 安装

建议放在 OpenClaw 的 skills 工作区；`xiaohu-wechat-format` 是部分主题使用的兄弟目录依赖。

```bash
mkdir -p ~/.openclaw/workspace/skills
git clone --depth 1 https://github.com/harryper/wechat-studio.git \
  ~/.openclaw/workspace/skills/wechat-studio
git clone --depth 1 https://github.com/xiaohuailabs/xiaohu-wechat-format.git \
  ~/.openclaw/workspace/skills/xiaohu-wechat-format
cd ~/.openclaw/workspace/skills/wechat-studio
mkdir -p clients
pip install -r requirements.txt
```

仓库已自带使用环境变量占位符的 `config.yaml`，通常不需要复制配置文件。`config.example.yaml` 仅用于查看单供应商和多供应商的完整写法。

## 配置

推荐在项目根目录创建不入库的 `.env`：

```dotenv
# Web 生成文章默认使用 MiniMax 的 Anthropic Messages 兼容接口
MINIMAX_API_KEY=your-minimax-key
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_AUTH_TOKEN=your-minimax-key
ANTHROPIC_MODEL=MiniMax-M3

# 创建微信草稿时必需
WECHAT_APPID=wx_your_appid
WECHAT_SECRET=your_appsecret

# 可选的图片生成回退；均未配置时使用本地占位图
OPENAI_API_KEY=sk-...

# Web 登录，正式部署务必修改
APP_PASSWORD=a-strong-password
APP_COOKIE_SECRET=a-long-random-secret

# D1 数据 Worker；Compose 已提供当前部署地址
D1_API_URL=https://wechat-studio-data.harryperlau.workers.dev
```

`config.yaml` 支持 `${VAR}` 和 `${VAR:-default}`，不要在仓库文件中写入真实密钥。未设置 `APP_PASSWORD` 时，开发环境默认密码为 `asdf123456`；这只适合本机测试。

## 启动 Web 工作台

```bash
docker compose up -d --build
curl -fsS http://127.0.0.1:9997/api/health
```

浏览器访问 `http://localhost:9997`。Compose 默认从 `../xiaohu-wechat-format` 挂载排版引擎；若它位于其他目录，可在 `.env` 中设置绝对路径：

```dotenv
XIAOHU_FORMAT_DIR=/absolute/path/to/xiaohu-wechat-format
```

生成请求会立即返回任务 ID，页面通过轮询显示写作、配图、排版和质量检查进度。任务状态、文章正文和内容状态统一保存在 Cloudflare D1，所以刷新页面后可以继续查看；后台生成线程仍在本机执行，容器或服务重启后任务记录仍会保留，但未完成任务需要重新提交。

Compose 从 Git 忽略的 `.d1_api_token` 读取 Worker 服务令牌，并以 Docker secret 挂载。首次部署数据 Worker和迁移旧数据：

```bash
npx wrangler deploy
python3 scripts/migrate_web_state_to_d1.py \
  --api-url https://wechat-studio-data.harryperlau.workers.dev \
  --token-file .d1_api_token
```

## OpenClaw 与 Web 的流程

两种入口共用文章、图片、排版和发布契约，但执行方式不同：OpenClaw 由 `SKILL.md` 编排工具调用，Web 由后台任务流水线执行。

```text
1. 选择知识库主题和写作框架
2. 读取可选客户 Style/Playbook，生成 Markdown 长文
3. 生成封面 + 4 张内文图
4. 生成主题 HTML，保存历史和质量检查结果
5. 在线编辑、换主题，或按文章/全部图片/单张图片重新生成
6. 用户确认后创建微信草稿
```

发布时会自动：

- 从首个 H1 提取微信标题，并从发布正文移除 H1 和内部分类元数据；
- 识别文件名为 `cover.jpg`、`cover.png`、`cover.webp` 或 `cover.gif` 的图片作为封面；
- 从正文移除封面图，上传其余本地图片并替换链接；
- 追加“本文为逻辑梳理，非学术研究”声明。

## 客户 Style / Playbook

每个客户使用独立目录；`clients/` 默认不进入 Git，Compose 会只读挂载到容器：

```text
clients/acme/
├── style.yaml     # tone、voice、content_style、blacklist
└── playbook.md    # 客户专属写作规则
```

在 Web 中选择客户后，Style/Playbook 会进入写作提示词，Blacklist 会参与发布前检查。AI 痕迹分为 `0–100`，越低表示规则检测到的模板化痕迹越少；它是启发式提示，不是内容真实性结论。

## CLI

```bash
python3 toolkit/cli.py themes
python3 toolkit/cli.py gallery article.md --no-open -o theme-gallery.html
python3 toolkit/cli.py preview article.md --theme terracotta --no-open
python3 toolkit/cli.py publish article.md --cover cover.png --title "标题"
```

可选的运营和学习工具：

```bash
python3 scripts/fetch_hotspots.py --limit 20
python3 scripts/humanness_score.py article.md --verbose
python3 scripts/fetch_stats.py --client CLIENT --days 7
python3 scripts/learn_edits.py --client CLIENT --draft draft.md --final final.md
```

## 升级与部署

升级前先确认本地改动；下面的命令不会替你处理冲突：

```bash
git status --short
git pull --ff-only
docker compose up -d --build
curl -fsS http://127.0.0.1:9997/api/health
```

选题、正文、历史、任务和发布状态保存在 D1，重新构建镜像不会删除。`webapp/_data/workdirs/` 只保存排版 HTML 和图片等本地运行产物。

## 验证

```bash
python3 -m pytest -q
python3 -m compileall -q toolkit scripts webapp
python3 scripts/diagnose.py --json
docker compose config -q
```

## 常见问题

- **生成时报 `ANTHROPIC_BASE_URL 未设置`**：在 `.env` 配置兼容接口地址、令牌和模型，然后重建或重启容器。
- **图片都是占位图**：检查至少一个生图 API Key；任务详情和 `image-status.json` 会记录每张图的结果。
- **xiaohu 主题不可用**：确认兄弟项目存在，或通过 `XIAOHU_FORMAT_DIR` 指向其绝对路径。
- **客户列表为空**：先创建 `clients/<客户名>/style.yaml`，然后确认 Compose 已挂载 `./clients:/app/clients:ro`。
- **微信发布失败**：运行 `python3 scripts/diagnose.py --json`，检查 AppID、Secret、IP 白名单和封面文件。
- **任务长时间停在运行中**：若服务期间发生过重启，请从内容库重新提交；任务错误和阶段可在 D1 中查询。

## 目录

```text
wechat-studio/
├── SKILL.md                 # OpenClaw 编排指令
├── webapp/                  # Flask 工作台、异步任务和预览历史
├── toolkit/                 # 排版、生图、微信 API 和发布 CLI
├── scripts/                 # 写作、选题、检测和学习工具
├── references/              # 知识库与按需加载的写作规范
├── toolkit/themes/          # 38 套主题 YAML
├── clients/                 # 本地客户配置，不进入 Git
└── dist/openclaw/           # OpenClaw 分发包
```

MIT · <https://github.com/harryper/wechat-studio>
