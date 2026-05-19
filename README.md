# WeChat Studio

公众号 AI 内容工作台：从热点抓取到草稿箱推送，一句话完成全部流程。

## 一句话安装

```bash
git clone --depth 1 https://github.com/harryper/wechat-studio.git ~/.openclaw/skills/wechat-studio
cd ~/.openclaw/skills/wechat-studio && pip install -r requirements.txt
```

安装后对 OpenClaw 说「写一篇公众号文章」即可触发完整流程。

## 环境配置

```bash
# 复制并填入你的密钥
cp config.example.yaml config.yaml

# 或者直接设置环境变量（config.yaml 会自动读取）
export WECHAT_APPID="wx_your_appid"
export WECHAT_SECRET="your_appsecret"
export OPENAI_API_KEY="sk-..."          # GPT Image 生图
export DOUBAO_API_KEY="your_volc_key"    # 豆包 fallback
```

`config.yaml` 中的 `${VAR}` 语法会自动从环境变量展开，无需在文件中存明文密钥。

## 核心功能

| 功能 | 说明 |
|------|------|
| 热点抓取 | 微博 / 头条 / 百度热搜 |
| AI 写作 | 选题 → 框架 → 写作 → SEO → 质量自检 |
| 视觉 AI | 封面 + 内文配图（GPT-Image-2 优先，豆包降级） |
| 排版引擎 | **38 套主题**（原生 + xiaohu 33 套），支持容器语法 |
| 草稿箱发布 | 直接推送到公众号草稿箱 |
| 效果复盘 | 微信数据 API 回填阅读/分享/点赞 |
| 风格学习 | 导入已发布文章，建立个人风格库 |

## 快速开始

```
你：写一篇公众号文章
你：看看有什么主题              → 主题画廊
你：换成 terracotta 主题        → 切换主题
你：看看文章数据怎么样          → 效果复盘
你：学习我的修改                → 风格飞轮
```

## 排版主题

38 套主题，分为两类：

- **xiaohu 引擎（33 套）**：完整容器语法支持，:::dialogue / :::callout 等
- **原生引擎（5 套）**：`terracotta` / `sspai` / `coffee-house` / `newspaper` 等

```bash
# 预览全部 38 套主题
python3 toolkit/cli.py gallery article.md --no-open -o theme-gallery.html

# 查看主题列表
python3 toolkit/cli.py themes
```

## CLI 工具（可选）

```bash
# 排版预览
python3 toolkit/cli.py preview article.md --theme terracotta

# 推送到公众号草稿箱
python3 toolkit/cli.py publish article.md --cover cover.png --title "标题"

# 抓热点
python3 scripts/fetch_hotspots.py --limit 20

# 微信数据复盘
python3 scripts/fetch_stats.py --client zhulv --days 7
```

## 目录结构

```
wechat-studio/
├── SKILL.md                      # 主管道（触发后加载）
├── config.yaml                   # 环境变量注入，无明文密钥
├── toolkit/
│   ├── cli.py                    # preview / publish / gallery
│   ├── publisher.py              # 微信草稿箱 API
│   ├── image_gen.py              # 多 provider 生图（含 fallback）
│   ├── xiaohu_formatter.py       # xiaohu 引擎（33 套主题）
│   └── themes/                   # 38 套主题 YAML
├── scripts/
│   ├── fetch_hotspots.py         # 多平台热点抓取
│   ├── fetch_stats.py            # 微信数据回填
│   ├── humanness_score.py        # 文章质量检测
│   └── learn_edits.py            # 风格学习
└── references/                   # 按需加载的规范文档
```

## 环境变量参考

| 变量 | 必填 | 说明 |
|------|------|------|
| `WECHAT_APPID` | ✅ | 微信公众号 appid |
| `WECHAT_SECRET` | ✅ | 微信公众号 secret |
| `OPENAI_API_KEY` | ✅ | GPT-Image-2 生图 |
| `DOUBAO_API_KEY` | 选 | 豆包/即梦 fallback 生图 |

不填也能跑，自动降级为本地 HTML 预览 + 图片提示词输出。

---

MIT · https://github.com/harryper/wechat-studio