# Web 模型设置中心

日期：2026-09-05
状态：设计已确认，待用户审阅

## 背景

WeChat Studio 当前只从进程环境读取模型配置：写稿固定使用 Anthropic Messages 兼容接口，生图从 `config.yaml` 和 `IMAGE_PROVIDER_ORDER` 构造自动回退链。Web 页面无法查看或修改 Provider、模型、Base URL 与 API Key，保存后也不能立即影响新任务。

本设计参考 MoneyPrinterTurbo 的两个边界：Provider 的静态能力由 Registry 集中声明；后台任务使用提交时的配置快照，不受后续设置修改影响。WeChat Studio 保持更小的范围，只增加实际需要的两种写稿协议与现有生图能力。

## 目标

1. 在 Web 页右上角增加“设置”按钮，通过弹窗配置写稿模型和生图模型。
2. 写稿支持 `OpenAI-compatible` 与 `Anthropic Messages` 两种协议。
3. 生图只调用用户选中的一个 Provider 和模型；失败时任务直接失败，不自动回退，也不创建占位图。
4. API Key、Base URL 与模型设置持久保存在本机，容器重启后仍然有效。
5. 已登录用户可以在设置弹窗查看完整 API Key。
6. 设置修改只影响之后提交的新任务，已排队或正在运行的任务使用提交时快照。
7. Web 的密钥和完整设置不进入 D1、任务 payload、文章历史或日志。
8. 保持 CLI/OpenClaw 现有 `.env/config.yaml` 行为不变。

## 非目标

- 不完整移植 MoneyPrinterTurbo 的供应商清单、设置导入导出、密钥备份或多语言系统。
- 不支持 Gemini、Qwen Native、Azure OpenAI 等额外写稿协议。
- 不为 Web 生图保留供应商回退链。
- 不允许远程 D1 保存或同步 API Key。
- 不恢复服务重启前未完成任务；这类任务仍需重新提交。

## 用户界面

页面右上角现有“健康检查”“退出”之前增加 `⚙ 设置` 按钮。点击后打开中等宽度的模态框，包含“写稿模型”和“生图模型”两个标签页。

### 写稿模型

- 协议：`OpenAI-compatible` 或 `Anthropic Messages`。
- 服务商预设：MiniMax、OpenAI、Anthropic、Kimi、DeepSeek、豆包和自定义。
- 模型名称：可编辑文本框。
- Base URL：可编辑文本框。
- API Key：密码框，眼睛按钮可切换为完整明文。
- “测试连接”：使用当前表单值发送一个要求只回复 `OK` 的极短请求，显示 Provider、模型、耗时和成功或脱敏错误。

预设只填充协议、默认模型和 Base URL；用户仍可覆盖所有字段。切换预设不得覆盖用户已经为其他 Provider 保存的凭据。

### 生图模型

- 服务商预设：cliproxy/OpenAI Images、Seedream、MiniMax 和自定义 OpenAI-compatible。
- 模型名称、Base URL、API Key：均可编辑。
- “测试生图”：点击后再次确认“本次测试会实际生成图片并产生费用”。确认后使用该 Provider 支持的最小测试尺寸生成一张中性测试图，并在弹窗显示缩略图。
- 页面不展示或保存回退顺序；每个 Web 任务只使用当前选中的一个模型。

### 保存与生效

底部提供“取消”和“保存设置”。保存成功后无需重启。弹窗显示“仅影响之后提交的新任务”；正在执行任务不变。API Key 默认掩码，但按用户要求，已登录浏览器可以请求并显示完整值。

## Provider Registry

新增集中 Registry，供前端元数据接口、保存校验和运行时调用共同使用。每个 Provider 声明：

```text
id
label
kind                 # writing / image
adapter              # openai_compatible / anthropic_messages / image provider key
default_model
default_base_url
requires_api_key
requires_base_url
supports_connection_test
test_size             # 仅生图 Provider；最小受支持测试尺寸
```

Provider 默认值属于代码能力声明，不直接写入用户配置。用户没有覆盖时动态采用 Registry 当前默认值，避免未来升级默认模型后被旧配置永久固定。

写稿 Provider 只映射到两个适配器：

- `openai_compatible`：调用 Chat Completions 兼容接口。
- `anthropic_messages`：调用 Anthropic Messages 兼容接口。

生图 Registry 复用 `toolkit/image_gen.py` 已有 Provider 实现；自定义 OpenAI-compatible 生图使用现有 OpenAI Images 适配器。

## 本机持久化

新增 `webapp/model_settings.py`，将配置写入：

```text
webapp/_data/model-settings.json
```

文件包含 schema version、写稿配置和生图配置。保存使用同目录临时文件、`fsync` 和原子替换；最终权限强制为 `0600`。父目录沿用已有 bind mount，因此容器重建和重启不会丢失设置。

API Key 按用户要求以可恢复形式保存在本机文件中，并可返回给已登录浏览器。本设计不声称本地静态加密：若加密密钥与配置文件存放在同一主机，无法抵御获得同等文件权限的攻击者。安全边界是 Linux 文件权限、Web 登录和禁缓存响应。

首次读取时如果文件不存在，从当前 `.env/config.yaml` 导入一次：

- 写稿导入 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`，协议为 `anthropic_messages`。
- 生图读取 `IMAGE_PROVIDER_ORDER` 的第一项，并从 `config.yaml` 展开对应模型、Base URL 和 API Key。
- 导入后写入本机设置文件；不反向修改 `.env` 或 `config.yaml`。

设置文件 JSON 损坏时不覆盖原文件。API 返回可诊断错误，Web 暂时回退到 `.env/config.yaml`，弹窗明确提示当前未使用损坏文件。

## Web API

新增以下登录保护端点：

```text
GET  /api/model-settings
PUT  /api/model-settings
POST /api/model-settings/test-writing
POST /api/model-settings/test-image
```

`GET` 返回 Registry、当前有效设置和完整 API Key。四个端点全部设置：

```http
Cache-Control: private, no-store
Pragma: no-cache
```

`PUT` 验证 Provider、适配器、模型名、API Key、Base URL 和 Registry 声明的必填项。Base URL 只接受 `http` 或 `https`，拒绝 URL userinfo；允许 `localhost`、`127.0.0.1` 和 `host.docker.internal`，以支持本机代理。

两个测试端点接收尚未保存的表单配置，因此用户可以先测试再决定是否保存。测试请求本身不会修改当前设置。生图测试要求请求体显式携带 `confirm_charge: true`。

## 写稿适配器

从 `scripts/write_article.py` 中分离协议调用，建立统一接口：

```text
generate(prompt, settings, max_tokens, timeout) -> str
test_connection(settings) -> ConnectionResult
```

`OpenAI-compatible` 使用现有 `requests` 依赖向规范化后的 `{base_url}/chat/completions` 发送请求，不新增 OpenAI SDK；`Anthropic Messages` 延续当前 Anthropic SDK 行为。两者统一处理空响应、Markdown 清洗、超时和错误脱敏。文章提示词构造与正文清洗逻辑保持在 `write_article.py`。

## 生图严格模式

`toolkit/image_gen.py` 现有 CLI/OpenClaw 回退链保持不变。Web 调用新增显式的单 Provider 配置，并启用严格模式：

1. 只构建选中的一个 Provider。
2. 任意图片调用失败即抛出异常。
3. Web 不捕获异常生成 PIL 占位图。
4. 任务标记失败；已经生成的中间图片保留在 workdir 供诊断，但不能形成成功预览。

重生全部图片或单张图片时使用点击重生当刻的当前设置，而不是文章最初使用的模型。

## 任务配置快照

模型设置提交时完成快照：

```text
浏览器提交生成/重生
→ Flask 在请求线程读取并深拷贝当前模型设置
→ D1 创建不含密钥的任务记录
→ 完整快照只作为参数传入 ThreadPoolExecutor
→ pipeline 使用该快照完成整个任务
```

D1 payload 只记录非敏感审计字段：协议、Provider ID 和模型名；不记录 API Key，也不记录可能带敏感查询参数的完整 Base URL。后台线程不在执行中重新读取当前设置。

服务重启会丢失进程内快照，但当前系统本来也不会恢复未完成线程；历史任务保留失败或中断状态，用户重新提交时使用最新设置。

## 错误、安全与日志

- API 和日志错误统一清除 URL userinfo、`api_key/token/key/secret/password` 查询参数、Authorization Header 和已知 API Key 原文。
- 日志只记录协议、Provider ID、模型名、Base URL 主机名、阶段和耗时。
- 设置 API 受现有 HMAC 登录 Cookie 保护。任何获得工作台密码的人都能按产品要求查看完整密钥；README 和弹窗需明确这一边界。
- 前端不得把设置写入 `localStorage`、URL、DOM data 属性或控制台。
- API 响应禁缓存；页面关闭弹窗时清空输入框 DOM 值，重新打开再从服务端加载。
- 生图测试产生的原图只放在临时目录，响应生成缩略图后删除；不进入 D1、文章历史或 workdir。

## 测试

实现遵循 TDD。

### Registry 与持久化

- Provider ID 唯一，写稿 Provider 只使用两种允许协议。
- 默认值解析与用户覆盖行为正确。
- 首次从 `.env/config.yaml` 导入后不反向修改源文件。
- 设置文件原子写入且权限为 `0600`。
- 损坏 JSON 不被覆盖，并产生可诊断回退状态。

### 协议适配器

- OpenAI-compatible 请求使用正确模型、Base URL、Key 和 Chat Completions 消息结构。
- Anthropic Messages 请求保持当前兼容接口行为。
- 两种响应均能提取正文并拒绝空响应。
- 超时、认证错误和带敏感 URL 的错误会被脱敏。

### Web API 与 UI

- 未登录访问四个设置端点返回 401。
- `GET` 按要求返回完整 Key，同时携带禁缓存响应头。
- `PUT` 拒绝未知 Provider、非法协议、缺失必填项和非法 Base URL。
- 测试连接使用未保存表单值且不修改持久设置。
- 生图测试缺少 `confirm_charge` 时拒绝请求。
- 弹窗标签切换、密钥显隐、取消、保存和错误状态正常。

### 任务语义

- 保存后新任务使用新设置。
- 已排队任务继续使用旧快照。
- D1 job payload、结果和日志中不存在 API Key。
- Web 生图失败时任务失败且没有占位图；CLI/OpenClaw 原有回退链测试继续通过。
- 重生操作使用提交时当前设置。

## 预期文件变化

| 文件 | 作用 |
|---|---|
| `toolkit/model_registry.py` | Provider 与默认值的单一声明源 |
| `toolkit/llm_adapters.py` | OpenAI-compatible 与 Anthropic Messages 调用 |
| `webapp/model_settings.py` | 本机设置读取、迁移、校验与原子保存 |
| `webapp/app.py` | 设置 API、测试端点和任务快照传递 |
| `webapp/pipeline.py` | 接收并使用任务模型快照 |
| `scripts/write_article.py` | 通过适配器写稿 |
| `webapp/render.py` | Web 严格单 Provider 生图 |
| `toolkit/image_gen.py` | 增加显式单 Provider 调用入口，保留旧回退链 |
| `webapp/templates/index.html` | 右上角按钮、设置弹窗与交互 |
| `tests/` | Registry、持久化、API、适配器、快照和 UI 回归测试 |
| `README.md`、`.env.example` | 配置优先级、安全边界和迁移说明 |

## 验收标准

1. 用户可在右上角打开设置，配置并持久化两种写稿协议和一个生图模型。
2. API Key 可显隐，重启容器后仍保留，且只存在本机设置文件。
3. 写稿和生图测试均使用未保存表单值；生图测试必须二次确认费用。
4. 新任务无需重启即可采用新设置；运行中任务不受修改影响。
5. Web 生图只调用一个选中模型，失败即报错。
6. D1、任务记录、文章历史、浏览器存储和日志均不包含 API Key。
7. CLI/OpenClaw 行为保持兼容。

## 参考

- MoneyPrinterTurbo 设置入口、弹窗与运行时快照：<https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/refs/heads/main/webui/Main.py>
- MoneyPrinterTurbo Provider Registry：<https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/refs/heads/main/app/models/llm_provider.py>
- MoneyPrinterTurbo 协议适配与错误脱敏：<https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/refs/heads/main/app/services/llm.py>
