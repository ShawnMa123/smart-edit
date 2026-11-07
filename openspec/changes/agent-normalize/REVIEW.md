# A 的 review 清单

> 你的义务**不止在 `agent-normalize/` 里**。下面三块都要看。

---

## 1. 你自己这个 change（必读）

```text
agent-normalize/
  proposal.md                       为什么做、边界、接缝
  design.md                         实现策略、判定细节、失败降级
  specs/normalization/spec.md       8 条 Requirement —— 这是验收标准
  tasks.md                          36 个 task
```

**重点看这三条**，它们是你和别人的分歧最容易发生的地方：

| 条目 | 内容 | 为什么重要 |
|---|---|---|
| `span` 粒度 | MUST 是最小可定位片段，不含"申请人：" | B 的一致性比对、你的 `provenance_check` 都依赖它 |
| `value` 大小写 | 保留原文，不做 upper() | 若你提前大写，合规场景要展示的客户原文就没了 |
| `parse → extract` 不写 `fields` | 未经规范化与三分类的值不满足契约 | 独立触发时下游会误用 |

---

## 2. 你的两项跨目录任务

### 2.1 `provenance_check` 检查器 · 在 `agent-audit/`

```text
openspec/changes/agent-audit/design.md   第 6 节 "provenance_check（A 实现）"
openspec/changes/agent-audit/tasks.md    第 3 节，7 个 task
```

**为什么交给你**：写这个检查器必须先精确回答三个问题 ——

1. `span` 取多长才算"最小片段"？上限多少？
2. 归一化包含哪些变换？（空白 / 全半角 / 连字符 / 引号）
3. `span` 跨行、跨页时怎么处理？

这三条**是 Agent 1 的核心定义**。由 C 代写，你可以一直含糊；你写，就必须定下来。

**硬要求**：这个检查器 MUST 调用共享层的 `normalize_ws`（`app/parsing/normalize.py`），
不得自己实现一份。否则你的 `extracted` 判定和 Agent 4 的校验会用两套规则，
一旦分叉，全部字段被判不合规且极难定位原因。

### 2.2 银行内部政策语料 · 在 `agent-regulatory/`

```text
openspec/changes/agent-regulatory/tasks.md    1.2
```

提供 10 条内部政策摘要，由 C 负责切块与检索。
**你不写代码，只提供内容** —— 因为法规内容写错比代码写错危险得多。

---

## 3. 必读的接缝契约

```text
openspec/changes/poc-skeleton/specs/agent-contract/spec.md     ← 30 分钟，最重要
openspec/changes/poc-skeleton/design.md                       契约结构定义
```

`agent-contract` 里有 7 条 Requirement，其中**接缝一（A → B）和接缝二（A → C）是你的义务**：

| 接缝 | 你要保证 |
|---|---|
| A → B | `value` 保留原文大小写；`source.span` 是最小片段；`confirmed=false`、`edited_by_user=false`；`notes` 为 `[]` 不是 `null`；字典外字段只进 `extra_fields` |
| A → C | `docs[].full_text` 与原文逐字一致，不是摘要；`business_type` 只由你写 `EditState` |
| 全体 → D | 每个字段至少一条 `emit`；每次模型调用记 `model` + `prompt_hash`；跳过记 `op="pass"` 带理由，不记 `drop` |

---

## 4. 请回答这三个问题

不要回答"同意"，请回答**做不到的地方**：

1. **`span` 最小片段的边界**：原文写 `申请人：ABC TRADING PTE LTD 地址：新加坡`，
   `span` 取 `ABC TRADING PTE LTD`。但原文若是 `ABC TRADING PTE LTD（以下简称"申请人"）`，
   `span` 该取到哪里？给出你的规则。

2. **`parse → extract` 不写 `fields`**：这意味着独立触发"只跑抽取"时，
   前端拿不到 `fields`。这个限制你能接受吗？如果不能，说清楚你需要什么。

3. **归一化规则清单**：空白折叠、全半角统一、连字符归一（`‐‑–—` → `-`）、引号统一。
   还有别的需要归一的情况吗？这份清单会写进 `normalize_ws`，你的判定和 Agent 4 的校验共用它。

---

## 5. 现在就能开工，但有一个前置

| 能否开工 | 说明 |
|---|---|
| ✅ `parse` 的 PDF 解析 | 可以先用裸 dict 写，等 `state.py` 落地再套 |
| ✅ `fields.yaml` 起草 | 不依赖任何代码 |
| ✅ `extract` 的 prompt 调试 | 不依赖契约 |
| ⚠️ `normalize` 的三分类判定 | 需要 `state.py` 的 `FieldValue` / `Source` 定义 |

`app/state.py` 目前还没写出来（`poc-skeleton` 的 tasks 2.1-2.4）。如果你需要它才能开始，
说一声，我优先做出来。
