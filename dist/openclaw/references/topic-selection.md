# 选题评估规则（知识科普轮转）

## 你的角色

你是一个公众号选题编辑。你的目标是从知识科普主题库中挑出下一个值得写的主题——评估它的写作潜力、框架适配度、与近期内容的差异度。

主题不再来自实时热点，而是来自结构化的 `references/knowledge-corpus.yaml` 主题库（60 个主题，10/类）。

## 输入

- `references/knowledge-corpus.yaml` 当前待评估主题（Step 2 选定）
- 客户 `style.yaml` 中的：`topics`、`target_audience`、`blacklist`、`content_style`
- 客户 `history.yaml` 中的：已发布文章的 `topic_id` / `category` / `stats`
- `references/topic-patterns.md`（如有，pattern 匹配）

## 评估维度

对每个候选主题，按三个维度打分（1-10）：

### key_points 覆盖度（权重 40%）

看 `key_points` 能否撑起写作框架：

- 3-5 条 key_points 都有清晰角度（起源 / 机制 / 案例 / 应用）→ 8-10 分
- 3-4 条，角度清晰但某条偏薄 → 6-7 分
- 3 条以下，或多条角度重复（都在讲案例）→ 3-5 分
- key_points 缺失 / 仅 1-2 条无法支撑 2500+ 字 → 1-2 分

**判断标准**：是否能直接对应 `frameworks-academic.md` 的 §1-§5 五段结构？每段至少要有一条 key_point 兜底。

### origin 清晰度（权重 30%）

看 `origin` 字段能否撑起框架 §1（起源段）：

- origin 包含具体人名 + 年份 + 关键事件（如 "1974 年 Tversky 与 Kahneman 数字轮盘实验"）→ 8-10 分
- origin 有时间但缺具体人物或事件 → 5-7 分
- origin 模糊（"20 世纪提出的概念"）→ 2-4 分
- origin 缺失或与 key_points 矛盾 → 0-1 分

**判断标准**：读者读完 §1，能不能用一句话讲清"这个概念是谁、什么时候、为什么提出的"？

### 与近期主题的关联度（权重 30%）

看与 `history.yaml` 最近 30 天的差异度：

- 与最近 7 天文章**不同 category**且**不同主题方向** → 8-10 分
- 与最近 7 天同 category 但**不同主题**（如 kb-001 幸存者偏差 → kb-002 锚定效应）→ 5-7 分
- 与最近 7 天**同主题**（如两篇都讲锚定效应）→ 1-3 分（避免连写同一概念）
- 与 7-30 天同 category 但不同主题 → 6-8 分（可接受，不扣分）
- **连写同 category**：同一 category 在最近 3 篇内出现 ≥ 2 次 → 综合评分扣 2 分，标注"⚠️ category 重复"

**判断标准**：读者连续看 3 篇，是否会觉得"又是一个 XX 偏差"？

## 综合评分

```
总分 = key_points 覆盖度 × 0.4 + origin 清晰度 × 0.3 + 关联度 × 0.3
```

满分 10 分；推荐阈值 ≥ 6.5 分。

## 输出格式

列出当前选定的 1 个主题（如交互模式则列出 Top 3 候选），每个包含：

```yaml
### 选题 {序号}: {选题标题}（kb-{id}，总分 X.X）

- category: {cognitive_bias / decision_theory / philosophy / psychology / economics / paradox}
- 对应标题（20-28字）："{为这个主题拟的公众号标题}"
- 切入角度：{1-2 句话说明怎么写、聚焦哪条 key_point}
- key_points 覆盖度：X/10 | origin 清晰度：X/10 | 关联度：X/10
- 推荐框架：{框架 1 起源-演变-影响 / 框架 2 原理-证据-应用 / 框架 3 经典实验-当代启示}
- 推荐理由：{为什么这个值得写，重点引用 key_points 中可展开的角度}
- 历史标记：{如果 history.yaml 近 3 篇出现同 category, 标注"⚠️ category 重复"}
- caution: {如 corpus 中 caution: yes, 标注"⚠️ 争议性概念, 写作时需谨慎处理"}
```

## Blacklist 拦截

标题拟定后，必须对生成的标题执行 blacklist 验证：

```bash
python3 {skill_dir}/scripts/check_blacklist.py "{候选标题}" --client {client}
```

- 命中 → 强制重生成（最多 2 次），每次重生成后再次验证
- 2 次仍命中 → 输出最强改写建议 (`suggestion` 字段)，自动模式放行 + warn；交互模式让用户决策
- 脚本报错 → 静默通过（warn-and-pass），不阻塞后续流程

## 历史去重规则

读取 `history.yaml` 中最近 30 天的文章记录，提取所有 `topic_id` 和 `category`。

- 当前 topic_id 已在历史中 → 跳过（Step 2 轮转已处理，这里是双保险）
- 同一 category 在**最近 3 篇**内出现 ≥ 2 次 → 综合评分扣 2 分
- 同一 category 在**最近 7 篇**内出现 ≥ 3 次 → 综合评分扣 3 分，标注"⚠️ category 过度集中"
- 超过 7 篇无此限制

## 历史效果闭环

如果 `history.yaml` 中有带 `stats` 的文章（阅读量、分享量），做以下分析：

1. **框架偏好**：统计每种 framework 的平均阅读量和分享率 → 推荐框架时，表现好的框架优先
2. **category 表现**：统计每个 category 的平均表现 → 关联度评分时，表现差的 category 加 1-2 分优先级（让好 category 多露脸），表现好的 category 正常排序
3. **标题风格**：分析高表现文章的标题特征（数字型/反直觉/痛点/提问）→ 拟标题时参考

不要强制套用——只作为加权信号，主题本身的质量仍然最重要。stats 数据不足 5 篇时跳过此分析。

## 注意

- corpus 主题自带"常青"属性——所有主题都不依赖时效性，不必再额外生成常青选题
- 主题耗尽由 `load_corpus.py` 自动循环处理（≥ 80% 告警，100% 从顶部循环），本文件不负责
- 推荐框架要根据 `key_points` 的角度组合来选，不要全推同一种
- `caution: yes` 的主题（如部分悖论、争议性概念）必须在写作时谨慎处理，避免绝对化表述
- 主题选择不依赖 SEO 关键词查询——corpus 主题本身就是经过筛选的长尾价值选题

---

## 候选输出格式 (Top 3 + pattern_tag)

交互模式下，每个候选除原有字段外，新增：

```yaml
### 选题 {序号}: {选题标题}（kb-{id}，总分 X.X）

- category: {category}
- 对应标题（20-28字）："{为这个主题拟的公众号标题}"
- 切入角度：{1-2 句话}
- key_points 覆盖度：X/10 | origin 清晰度：X/10 | 关联度：X/10
- 推荐框架：{框架 1 / 2 / 3}
- 推荐理由：{为什么这个值得写}
- 历史标记：{如近 3 篇同 category, 标注"⚠️ category 重复"}
- caution: {如 caution: yes, 标注"⚠️ 争议性概念"}

# === 新增字段 ===
- pattern_tag: "{framework × title_mode, 如 起源-演变-影响 × 反问/问句}"
  - 匹配自 `references/topic-patterns.md` 的 Pattern A/B/C...
  - pattern_match_score: 0.0-1.0 (1.0 = 完全命中, 0 = 不命中)
```

**模式匹配规则**:
1. 加载 `references/topic-patterns.md` 到上下文
2. 对每个候选主题，估算其 `framework`（基于 key_points 角度组合）和 `title_mode`（基于拟好的标题）
3. 在 pattern 库中查找精确匹配；若无精确，找 framework 相同 + title_mode 相近的（允许 ±1 容差）
4. 命中后，写入候选主题的 `pattern_tag` 字段，格式 `{framework} × {title_mode}`
5. `pattern_match_score`:
   - 1.0 = 精确匹配 pattern
   - 0.7 = framework 相同, title_mode 相近
   - 0.4 = 仅 framework 命中
   - 0.0 = 都不命中

**输出数量**:
- 自动模式（默认）：仅输出最终选定的 1 个
- 交互模式：输出 Top 3 候选，每个含 `pattern_tag` 对比
