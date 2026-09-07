# WeChat Studio

公众号 AI 内容工作台：从主题构思、长文写作和配图，到排版预览、在线修改和微信草稿箱发布。

当前版本：`1.5.0`

## 功能概览

- Web 工作台支持直接输入文章主题、关键要点、素材背景和自定义 Prompt；OpenClaw 可从 `references/knowledge-corpus.yaml` 的 30 个认知模型中选择主题。
- Web 写作支持 OpenAI-compatible 与 Anthropic Messages 两种协议，生成 2500–4000 字 Markdown 长文。
- Web 工作台异步生成 1 张封面和 4 张内文图；提示词按实际章节正文生成，五图保持统一视觉风格，并允许少量与场景和正文依据直接相关的解释文字。它只调用当前选中的一个模型；单张失败会使任务失败，不会自动回退或生成占位图。
- 提供 38 套主题、桌面/移动预览、Markdown 在线修改和本地文章历史。
- 支持重写文章、重生全部图片、重生单张图片及单独换主题。
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
pip install -r requirements.txt pytest
```

仓库已自带使用环境变量占位符的 `config.yaml`，通常不需要复制配置文件。`config.example.yaml` 仅用于查看单供应商和多供应商的完整写法。

## 配置

推荐直接 `cp .env.example .env` 后填值；`.env.example` 是变量清单的单一来源。首次打开 Web 工作台且本地模型设置文件尚不存在时，Web 会从 `.env/config.yaml` 导入一次；之后继续使用 Web 设置不需要把密钥写回 `.env`。

推荐在项目根目录创建不入库的 `.env`：

```dotenv
# Web 生成文章默认使用 MiniMax 的 Anthropic Messages 兼容接口
MINIMAX_API_KEY=your-minimax-key
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=your-minimax-key
ANTHROPIC_MODEL=MiniMax-M3

# 图片默认按本机 gpt-image-2 → Seedream → MiniMax 的顺序生成
CLIPROXY_IMAGE_API_KEY=your-local-proxy-key
# 直接运行 CLI 时默认连接 127.0.0.1:8317；Compose 会自动改用宿主机地址
ARK_API_KEY=your-volcano-ark-key
# 供应商顺序，取值为 config.yaml 中的 id
IMAGE_PROVIDER_ORDER=cliproxy,seedream,minimax

# 创建微信草稿时必需
WECHAT_APPID=wx_your_appid
WECHAT_SECRET=your_appsecret

# 可选的 OpenAI 图片回退；默认关闭，启用后才会产生相关费用
OPENAI_API_KEY=sk-...

# Web 登录，正式部署务必修改
APP_PASSWORD=a-strong-password
APP_COOKIE_SECRET=a-long-random-secret

# 本地数据目录；Compose 默认把仓库内的 webapp/_data 绑定到容器
WS_DATA_DIR=
```

`config.yaml` 支持 `${VAR}` 和 `${VAR:-default}`，不要在仓库文件中写入真实密钥。未设置 `APP_PASSWORD` 时，开发环境默认密码为 `asdf123456`；这只适合本机测试。

### Web 模型设置边界

在工作台右上角的“设置”中配置写作和生图模型。以下规则是 Web 工作台、CLI 和 OpenClaw 的明确边界：

> Web 工作台优先使用 webapp/_data/model-settings.json；文件不存在时从 .env/config.yaml 导入一次。
>
> Web 设置只影响之后提交的新任务；CLI/OpenClaw 始终继续读取 .env/config.yaml。
>
> API Key 仅保存在本机，但任何获得工作台登录密码的人都能在设置页面查看完整值。
>
> Web 生图只调用当前选中的一个模型，失败时任务直接失败，不自动回退或生成占位图。

模型设置文件属于本机运行数据，不应提交或复制到其他机器；请将工作台登录密码视为可以读取这些本地 API Key 的凭据。

## 启动 Web 工作台

```bash
docker compose up -d --build
curl -fsS http://127.0.0.1:9997/api/health
```

第二条命令是供 Docker 和运维使用的服务探活检查；成功时返回 JSON，不是用户页面。日常使用直接打开 Web 工作台即可。

浏览器访问 `http://localhost:9997`。Compose 默认从 `../xiaohu-wechat-format` 挂载排版引擎；若它位于其他目录，可在 `.env` 中设置绝对路径：

```dotenv
XIAOHU_FORMAT_DIR=/absolute/path/to/xiaohu-wechat-format
```

生成请求会立即返回任务 ID，页面通过轮询显示写作、配图和排版进度。所有状态、文章正文和任务文件都保存在 `webapp/_data/` 下，跨页面刷新、Gunicorn worker 回收、容器重启和镜像重建都会保留。容器启动时遗留的 `queued` / `running` 任务会被标记为 `failed`，错误信息为“服务进程重启，任务已中断，请重新提交”。

## 数据存储

Web 工作台的内容保存在 `webapp/_data/`：

| 文件 / 目录 | 内容 |
|---|---|
| `webapp/_data/history.json` | 文章历史元数据、topic 快照和单调递增 ID |
| `webapp/_data/topics.json` | 用户创建的自定义选题；内置选题每次从 `references/knowledge-corpus.yaml` 加载 |
| `webapp/_data/jobs/<job-id>.json` | 异步任务状态（写作 / 配图 / 渲染） |
| `webapp/_data/workdirs/<article-id>/` | `article.md`、`article.html` 和图片等产物 |
| `webapp/_data/model-settings.json` | Web 工作台设置（首次启动从 `.env` 导入） |

历史记录按文章 ID 单调递增；删除文章不会复用 ID。**只有用户主动删除文章时**才会级联清理该文章的任务文件、`workdirs/` 下的产物和 `history.json` 中的记录；自定义选题独立保留以便被其他文章继续引用。

修改默认数据目录：设置 `WS_DATA_DIR`（容器内路径或主机绝对路径均可），所有读取和写入都会切换到该路径。Compose 默认通过 `./webapp/_data:/app/webapp/_data` 把主机目录挂载到容器，重建或重启容器时数据保留。

## OpenClaw 与 Web 的流程

两种入口共用文章、图片、排版和发布能力，但起点不同：Web 直接接收用户输入的主题和素材，OpenClaw 可从知识库选题并由 `SKILL.md` 编排工具调用。

```text
1. 在 Web 输入主题和素材，或由 OpenClaw 选择知识库主题和写作框架
2. 读取可选客户 Style/Playbook，生成 Markdown 长文
3. 生成封面 + 4 张内文图
4. 生成主题 HTML 并保存历史
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

在 Web 中选择客户后，Style/Playbook 会进入写作提示词。Blacklist 和 AI 痕迹分析仍可通过下方的独立运营工具按需执行。

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
python3 scripts/learn_edits.py --draft draft.md --final final.md
```

## 升级与部署

升级前先确认本地改动；下面的命令不会替你处理冲突：

```bash
git status --short
git pull --ff-only
docker compose up -d --build
curl -fsS http://127.0.0.1:9997/api/health
```

本地数据目录及其保留、删除规则见上方“数据存储”。其中的内容通过 Compose 挂载，在重新构建容器后继续保留。

## 验证

```bash
python3 -m pytest -q
python3 -m compileall -q toolkit scripts webapp
docker compose config -q
```

按需检查本机依赖、凭据和个性化配置：

```bash
python3 scripts/diagnose.py --json
```

该诊断命令发现缺失配置时会返回非零状态；根据 JSON 中的 `checks` 和 `recommendations` 补齐实际需要的项目即可。

## 常见问题

- **生成时报 `ANTHROPIC_BASE_URL 未设置`**：在 `.env` 配置兼容接口地址、令牌和模型，然后重建或重启容器。
- **xiaohu 主题不可用**：确认兄弟项目存在，或通过 `XIAOHU_FORMAT_DIR` 指向其绝对路径。
- **客户列表为空**：先创建 `clients/<客户名>/style.yaml`，然后确认 Compose 已挂载 `./clients:/app/clients:ro`。
- **微信发布失败**：运行 `python3 scripts/diagnose.py --json`，检查 AppID、Secret、IP 白名单和封面文件。
- **任务长时间停在运行中**：若服务期间发生过重启，请从历史记录重新生成，或重新提交文章；任务状态保存在 `webapp/_data/jobs/`。

## 目录

```text
wechat-studio/
├── SKILL.md                 # OpenClaw 编排指令
├── webapp/                  # Flask 工作台、异步任务和本地存储
├── toolkit/                 # 排版、生图、微信 API 和发布 CLI
├── scripts/                 # 写作、选题、检测和学习工具
├── references/              # 运行时知识库与按需加载的写作规范
├── toolkit/themes/          # 38 套主题 YAML
├── clients/                 # 本地客户配置，不进入 Git
└── dist/openclaw/           # 自动生成的 OpenClaw 运行时分发包
```

MIT · <https://github.com/harryper/wechat-studio>
