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
# 必填环境变量（config.yaml 会自动读取 ${VAR} 占位符）
export WECHAT_APPID="wx_your_appid"
export WECHAT_SECRET="your_appsecret"
export OPENAI_API_KEY="sk-..."          # GPT-Image-2 生图
export DOUBAO_API_KEY="your_volc_key"    # 豆包 fallback 生图

# 可选：将配置写入 config.yaml（敏感值用 ${VAR} 语法，无需明文）
cp config.example.yaml config.yaml
```

不填也能跑，降级为本地 HTML 预览 + 图片提示词输出。

## 工作流程（8 步）

```
用户说「写一篇公众号文章」
  │
  ▼
Step 1  确定客户 → 读取 clients/{name}/style.yaml
  │
  ▼
Step 2  热点抓取 → POST `https://api.yucoder.cn/api/hot/list` 聚合热榜（知乎/微博/虎扑/贴吧/B站/抖音），失败则补调用，最多1次
  │
  ▼
Step 2.5  历史去重 + SEO 评分 → 避开近7天已写选题
  │
  ▼
Step 3  选题生成 → 综合评分最高的题自动进入写作
  │
  ▼
Step 4  文章写作 → H1标题 + 1500-2500字 + 框架大纲
  │         （playbook 优先于通用写作规范）
  │
  ▼
Step 5  SEO优化 → 3个备选标题 + 摘要 + 5个标签 + 去AI痕迹
  │
  ▼
Step 6  视觉AI → GPT-Image-2 生成封面+2-3张内文图
  │         （GPT 失败 → 豆包降级）
  │         → file 校验 PNG 1536x1024 → 替换占位符
  │
  ▼
Step 7  排版发布 → 38套主题 → 微信草稿箱
  │         （xiaohu主题走专用引擎，其他走基础降级）
  │
  ▼
Step 8  写入 history.yaml → 回复用户（含编辑建议）
```

**默认全自动**，不需要停下来确认。说「交互模式」才在选题/框架/配图处暂停。

## 排版主题（38 套）

| 引擎 | 主题数 | 支持特性 |
|------|--------|---------|
| xiaohu 引擎 | 33 套 | 完整容器语法（:::dialogue / :::callout 等）+ 暗黑模式 |
| 原生引擎 | 5 套 | `terracotta` / `sspai` / `coffee-house` / `newspaper` 等 |

```bash
# 预览全部 38 套主题
python3 toolkit/cli.py gallery article.md --no-open -o theme-gallery.html

# 查看主题列表
python3 toolkit/cli.py themes
```

## 核心功能

| 功能 | 说明 |
|------|------|
| 热点抓取 | 微博 / 头条 / 百度热搜，评分排序 |
| AI 写作 | 选题 → 框架 → 写作 → SEO → 质量自检 |
| 视觉 AI | GPT-Image-2 优先，豆包降级；生成后 file 校验格式 |
| 排版引擎 | 38 套主题，xiaohu 引擎 vs 原生引擎路由 |
| 草稿箱发布 | 直接推送到公众号草稿箱 |
| 效果复盘 | 微信数据 API 回填阅读/分享/点赞 |
| 风格学习 | 导入已发布文章 → 建立个人风格库 |

## CLI 工具

```bash
# 排版预览（本地HTML）
python3 toolkit/cli.py preview article.md --theme terracotta

# 推送到公众号草稿箱
python3 toolkit/cli.py publish article.md --cover cover.png --title "标题"

# 抓热点
python3 scripts/fetch_hotspots.py --limit 20

# 微信数据复盘
python3 scripts/fetch_stats.py --client zhulv --days 7

# 文章质量检测
python3 scripts/humanness_score.py article.md --verbose
```

## 目录结构

```
wechat-studio/
├── SKILL.md                      # 主管道（AI Agent 触发后加载）
├── config.yaml                   # 环境变量注入，无明文密钥
├── toolkit/
│   ├── cli.py                    # preview / publish / gallery / themes
│   ├── publisher.py              # 微信草稿箱 API
│   ├── image_gen.py              # 多 provider 生图（含自动 fallback）
│   ├── xiaohu_formatter.py       # xiaohu 引擎（33 套主题）
│   └── themes/                   # 38 套主题 YAML
├── scripts/
│   ├── fetch_hotspots.py         # 多平台热点抓取
│   ├── fetch_stats.py            # 微信数据回填
│   ├── humanness_score.py        # 文章质量检测（11 项）
│   └── learn_edits.py            # 风格学习飞轮
├── clients/                      # 客户配置（不在 git 中）
│   └── zhulv/
│       ├── style.yaml            # 风格配置
│       ├── history.yaml          # 发布记录
│       └── gpt-image-2-prompts.md # 客户级视觉规范
└── references/                   # 按需加载的规范文档
```

## 环境变量速查

| 变量 | 必填 | 说明 |
|------|------|------|
| `WECHAT_APPID` | ✅ | 微信公众号 appid |
| `WECHAT_SECRET` | ✅ | 微信公众号 secret |
| `OPENAI_API_KEY` | ✅ | GPT-Image-2 生图 |
| `DOUBAO_API_KEY` | 选 | 豆包/即梦 fallback |

---

MIT · https://github.com/harryper/wechat-studio