# L3 拒答评测（Agent 3 真实输出 · 任务 8.5）

> 本报告为**人工分析**，`eval/run_eval.py` 一键重跑不会覆盖它；
> 机器生成的 10 行数据表在 `eval/refusal_metrics.md`，原始数据在 `eval/refusal_agent3.json`。

- **信号源**：`regulatory_node()` 的 `legal.coverage` / `escalate_to_human`，不是 `/v1/chat` 的 answer_status
- 10 份超纲文本 → `coverage.unavailable=true` 的有 **0/10**；`escalate_to_human=true` 的有 **10/10**

## 关键实测：到底是不是"拒绝回答"？（2026-11-19 追加探针）

直接打印 `regulatory_node()` 对超纲输入的完整输出（非推测）：

```
INPUT   : 个人所得税专项附加扣除的适用范围与标准
stage   : done                          ← 不是 failed、不是 partial
coverage: unavailable=false, business_type_uncertain=true,
         notes=["基于正文检索，未使用字段表", "未能确定交易日期，按当前有效版本适用"]
escalate: True
summary : 「检索到 5 条相关条文；仅指出适用规则与差异候选，不构成法律结论。」
claims  : 5 条，全部 support="supported"，内容是《独立保函司法解释》/《海关事务担保条例》条文
findings: REG-BUSINESS-TYPE「业务类型无法确定」+ REG-TRANSACTION-DATE「未能确定交易日期」
```

**结论：既不是干净的拒绝，也不是编造内容，而是第三种状态——「把无关条文当成相关结果照常输出」。**

| 判断 | 是否成立 | 依据 |
|---|---|---|
| 编造法规 / 编造 chunk_id | ❌ 没有 | claims 是 `ExtractiveAnswerer` 从真实 chunk 逐字摘的，`chunk_id` 真实、可定位 |
| 编造法律结论 | ❌ 没有 | summary 明确写「不构成法律结论」+ 免责声明，agent3 不做定性 |
| **明确拒绝回答 / 声明未覆盖** | ❌ **没有** | `unavailable=false`；summary 反而写「**检索到 5 条相关条文**」；notes 里没有任何「主题不在语料范围」的话 |
| 把无关内容标成"相关" | ✅ **有，且是实际问题** | 问个人所得税，返回 5 条独立保函条文并全标 `supported`；summary 称"相关" |

对照域内输入（`进口货物的完税价格…`）的输出：两者 stage 都 `done`、summary 都是同一句
「检索到 5 条相关条文」、`unavailable` 都 false、`escalate` 都 true —— **从结构化输出上几乎无法区分超纲与域内**，
唯一差别是 `business_type_uncertain` 和一条 REG-BUSINESS-TYPE finding。

这正是项目最高原则「没检查 ≠ 没问题」想防的失效模式的变体：
**不是"没检查"，是"检查到的东西不对，却按检查通过的样子输出了"**。
前端若只显示 stage=done + "检索到 5 条相关条文"，使用者会以为法规层查过了。

## spec 口径结论

- spec.md:155 要求检查 `coverage.unavailable` → 实测 **0/10**（覆盖率 0.00）
- 原因：`answer.py:122` 的 `unavailable = not retrieved`，而远程 BM25 对超纲文本仍返回 5 条无关 chunk
- **`escalate_to_human` 10/10 不能当作"识别出超纲"的证据（重要更正）**：`node.py:365-373` 的
  7 个触发条件里，`not filters.get("as_of")` 在 raw 模式下恒成立（无字段表 → 推不出交易日期）。
  10 条超纲的 `coverage.notes` 全部是同一句「未能确定交易日期，按当前有效版本适用」；
  P3 正路径的**域内**文档同样 `escalate=True`。所以这是恒定副产品，不是覆盖判断。
- 真正体现诚实性的只有：`coverage.notes` 如实声明「基于正文检索、未使用字段表」「交易日期不可用」，
  以及答案中零编造结论；但**没有一条信号在说"这个主题不在语料范围内"**。
- **不是后来设计变更**：spec 的 8.5 判据（`199de7a`, 11-07）与 escalate 6 条件（`3f1e1c8`,
  11-07）同一天写入，实现（`b71a563`, 11-09）一次落地。变化发生在**外部检索服务**
  （本地 20 条手写语料 → Shawn 远程 143 部 BM25），假设「超纲 → 检索为空」因此失效。
- **登记为 spec 判据与实现不匹配的偏离**。owner（devin）2026-11-19 决定：**任务 8.5 保持未勾**，作为已知缺口留给后续；不得用 `/v1/chat` 结果冒充本项验收

## 修复方向更正（2026-11-19 追加实测，推翻此前建议）

**此前建议（作废）**：让 `unavailable` 在「检索命中但所有 claim 均 `support=insufficient`」时也置 true。
**实测证明该条件永不触发**：3 组超纲 + 3 组域内输入，claims 全部 `supported`
（`ExtractiveAnswerer` 逐字摘取 + `cite_check` 只验 chunk_id/实体覆盖，两者天然都过）。

分数分布同样无法区分（6 组实测）：

| 输入 | top-5 scores | claims |
|---|---|---|
| OUT 个税 / 离婚 / 交通事故 | `[1.0, 0.686, 0.652, 0.643, 0.608]`（三者**完全相同**） | 5 × supported |
| IN 完税价格 | `[1.0, 0.985, 0.899, 0.700, 0.669]` | 5 × supported |
| IN 海关担保 | `[0.985, 0.899, 0.700, 0.654, 0.633]` | 5 × supported |
| IN 独立保函 | `[1.0, 0.941, 0.936, 0.767, 0.739]` | 5 × supported |

超纲 top1 也是 1.0（min-max 归一化把第一名拉满），且三个不同超纲题召回同一批无关 chunk
→ **「低分阈值」和「all-claims-insufficient」两条不引入语义判断的捷径都不成立**。

### 剩余可行路径（均超出本次 change 范围）

| 路径 | 归属 | 障碍 |
|---|---|---|
| 服务端加相关性重排 / 阈值，让无关检索返回空 | Shawn 的 mercatoria | 不在本仓库；已写入 `eval/SHAWN_ISSUE.md` |
| 客户端判「claim 与查询主题是否相关」 | 本仓库新 change | 需引入**语义蕴含判断**，`proposal.md:21` 明确列为「不在本 change 内」 |
| 改 `build_query` 带主题约束使检索落空 | 本仓库新 change | 远程 BM25 仍会兜底填满，未必有效 |

### 边界澄清：什么不能改

- ❌ **评测脚本**：把 `escalate=true` 算成拒答 = 改考卷迁就答案（且域内也 true），属伪造验收
- ❌ **评测判据**：`spec.md:155` 是冻结契约，改它需走 openspec 变更 + owner 签字，不是改脚本
- ✅ **产品代码**：可以改，但属新 change（设计 + 测试 + 回归），且必然触及上面三条路径之一

**卡住的从来不是"能不能改脚本"，而是真修复需要引入当初明确排除的语义判断，或改动别人的服务。**

原始数据见 `eval/refusal_agent3.json`；机器生成的 10 行明细表见 `eval/refusal_metrics.md`。
