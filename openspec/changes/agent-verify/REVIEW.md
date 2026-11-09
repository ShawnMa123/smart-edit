# B 的 review 清单

> 你的义务在 `agent-verify/` 里，但**必须先读接缝契约**，否则会写错方向。

---

## 1. 先读这个（30 分钟，最重要）

```text
openspec/changes/poc-skeleton/specs/agent-contract/spec.md
```

7 条 Requirement。其中**接缝一（A → B）和接缝四（B → 闸门）是你的义务**：

| 接缝 | 你要知道 |
|---|---|
| A → B | `value` 保留原文大小写（你要比对时自己归一化）；`span` 是最小片段；`status` 三分类可信；字典外字段只在 `extra_fields` |
| B → 闸门 | 阻断项来自 `findings` 里 `blocking=true 且 resolved=false`；`blocking` 由 `requirements.yaml` 声明，不由 `severity` 推导；你 MUST NOT 写 `verification` |
| 全体 → D | 每条 Finding 要能在 trail 里找到 `emit`；产出后 `resolved=false` |

**最容易出错的**：`fields.yaml` 里每条约束带 `stage` 标签。
`stage=normalize` 归 A（把值转成合规形式），`stage=validate` 归你（业务上允不允许）。
**同一约束不得两人各实现一遍** —— 你要读 `agent-normalize/design.md` 的 `fields.yaml` 一节确认边界。

---

## 2. 你自己这个 change

```text
agent-verify/
  proposal.md                          边界 + 跨单据比对为何不做
  design.md                            节点、双判法、Finding 规则、失败降级
  specs/business-verification/spec.md  9 条 Requirement —— 验收标准
  specs/eval-benchmark/spec.md          离线评测的格式与口径
  tasks.md                             44 个 task
```

**三条最容易有分歧的**：

| 条目 | 内容 | 为什么这么定 |
|---|---|---|
| `not_found` 不阻断 | 交了但没抽出来 → `blocking=false` | 阻断会让柜员去追客户补一份已经交过的材料 |
| `blocking` 由规则声明 | 不按 `severity` 推导 | 有些 `critical` 只该提示（如筛查命中），有些必须拦 |
| 跨单据比对**不做** | 发票 vs 合同金额比对 | `fields` 键唯一，一个字段只能存一个值，无法表达"发票 500,000 / 合同 480,000"。这是契约级改动，POC 时间盒外 |

---

## 3. gold 格式已经写成 spec

原 `docs/evaluation.md` 的内容已搬进：

```text
openspec/changes/agent-verify/specs/eval-benchmark/spec.md
```

**你标注时照这个格式**，重点四条：

```json
// eval/gold/<sid>.json
{ "sample_id": "S01", "files": ["invoice.pdf"], "business_type": "guarantee",
  "fields": { "amount": {"value": "500000.00", "tolerance": "numeric"} } }
```

| tolerance | 比法 |
|---|---|
| `exact` | 归一化后全等 |
| `numeric` | 转 Decimal 后相等 |
| `date` | 转 ISO 日期后相等 |
| `fuzzy:<阈值>` | 相似度 ≥ 阈值 |

- `files` 只写 POC 支持的格式（文本型 PDF、粘贴文本、纯文本邮件），**不得含 Word / Excel / 扫描件**
- `eval/gold_rules/<sid>.json` 每项含 `kind` / `rule_id` / `severity` / `blocking` / `field_keys` / `note`
- 标注口径：**只标"业务上应该报什么"，不看模型实际输出**
- 分歧处两人各标一半再交叉复核，不得单人决定

指标必须**按字段类型分别报 P/R/F1**，不报总平均；另报**整份零错误率**与**推断率**。
L2 最关键的指标是 **blocking 漏报数**。

---

## 4. 请回答这三个问题

不要回答"同意"，请回答**做不到的地方**：

1. **`not_found` 不阻断**：如果客户确实交了提单但你抽不出来，系统不会拦。
   演示时这可能被问"为什么不拦"。你接受这个取舍吗？还是希望 `not_found` 也阻断（或至少 warn）？

2. **`requirements.yaml` 的具体内容从哪来**：tasks 1.4 写了"与业务方确认，不可自行推断"。
   你现在有渠道拿到真实要件清单吗？如果没有，你打算怎么处理（先写占位并标注，还是先做结构）？

3. **跨单据比对不做**：这是最容易被业务方问"为什么发票金额和合同金额不同也不报"的地方。
   你能接受在演示时主动说明这个限制吗？

---

## 5. 现在就能开工

你的 Agent 2 **不依赖任何代码**：

| 能做什么 | 说明 |
|---|---|
| ✅ `requirements.yaml` | 纯业务知识，不依赖 `state.py` |
| ✅ `eval/gold` 与 `gold_rules` 标注 | 纯人工，不依赖代码 |
| ✅ `check_rules` 的规则设计 | 逻辑确定，可先写成纯函数 |
| ⚠️ `check_fields` / `check_completeness` | 要 `state.py` 的 `FieldValue` 结构 |

`app/state.py` 还没写出来（`poc-skeleton` 的 tasks 2.1-2.4）。需要的话说一声，优先做。

---

## 6. 顺带一提

`poc-skeleton`（60 个 task：契约 + 共享层 + 主图 + 闸门）owner 还空着。
你的 Agent 2 是四个里代码量最小的（主要工作是 `requirements.yaml` 和标注），
如果你有余力，这块最适合你接 —— 而且写 `check_rules` 之前你本来就要先读懂 `fields` 的结构。

不强制，你判断。
