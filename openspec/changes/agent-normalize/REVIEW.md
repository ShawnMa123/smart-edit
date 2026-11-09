# A 的 review 清单（v2）

> 你的义务**不止在 `agent-normalize/` 里**。下面六块都要看。
> v2 相对上一版的关键变化：**三个"请你回答"的问题已经在 `design.md` 里定稿**（§7.1 / §7.2），
> 不再是待讨论项 —— 现在要你确认的是"这些规则能不能照做"，而不是"你怎么想"。

---

## 1. 你自己这个 change（必读）

```text
agent-normalize/
  proposal.md                       为什么做、边界、接缝、v2 变更清单
  design.md                         实现策略、判定细节、失败降级（v2 重写，14 节）
  specs/normalization/spec.md       10 条 Requirement / 48 个 Scenario —— 这是验收标准
  tasks.md                          11 节 · 69 个 task
```

**重点看这五条**，它们是你和别人最容易分歧、且一旦分歧代价最大的地方：

| 条目 | 内容 | 为什么重要 |
|---|---|---|
| `span` 粒度 | §7.2 五条边界规则 + `MAX_SPAN_LEN=200` | B 的一致性比对、你的 `provenance_check`、核对台的"跳回原文"全依赖它 |
| `value` 大小写 | 保留原文，不做 `upper()`；连 `normalize_ws` 都不折叠大小写 | 若你提前大写，合规场景要展示的客户原文就没了；若归一化折叠大小写，`provenance_check` 就验不出"模型改写了" |
| `parse → extract` 不写 `fields` | 只产出 `_candidates` | 未经规范化的候选值写进 `fields`，等于给下游一个"看起来可用"的假数据 |
| `normalize_ws` 五步 | NFKC → 零宽 → 连字符 → 引号 → 空白 | 少任何一步，名称/编号/带引号的条款号会成批假降级为 `inferred`，而这直接吃掉验收指标（`inferred` < 30%） |
| `missing` 占位 | `required` 无候选必须占位 | 不占位则 `missing` 是死枚举，且闸门与核对台无法区分"原文没写"与"没抽出来" |

---

## 2. 上一版留给你的三个问题：答案已定稿

| # | 问题 | 结论 | 位置 |
|---|---|---|---|
| 1 | `ABC TRADING PTE LTD（以下简称"申请人"）` 的 `span` 取到哪里 | 取 `ABC TRADING PTE LTD`：遇注释性开括号即截断，括号本身不入 span；另附栏目标签、分隔符、200 字符上限、跨页降级共 5 条规则，按序判断 | `design.md` §7.2 |
| 2 | `parse → extract` 不写 `fields` 这个限制能否接受 | **能，而且必须**。前端预览读 `_candidates`，并在 UI 上明确标注"未规范化、不可用于核对"。若产品坚持要 `fields`，那就等于要求"跳过三分类直接给结果"，这条接缝必须三人重开 | `design.md` §10 |
| 3 | 归一化规则清单还缺什么 | 上一版只有"空白 + 5 个全角标点"，本版补齐 NFKC / 零宽字符 / 连字符（`U+2010–U+2015`、`U+2212`）/ 引号（弯引号、`«»`、`「」`）；并明确**不做**大小写折叠、去标点、同义词换算 | `design.md` §7.1 |

> 这三条是 Agent 1 的核心定义。定了就写进 spec，别在 PR 里再讨论一次。

---

## 3. 你的两项跨目录任务

### 3.1 `provenance_check` 检查器 · 在 `agent-audit/`

```text
openspec/changes/agent-audit/design.md   第 6 节 "provenance_check（A 实现）"
openspec/changes/agent-audit/tasks.md    第 3 节，7 个 task
```

**v2 之后你有了明确依据**（以前只有"你自己想清楚"）：

- 判据：`status="extracted"` 但 `source` 为 `null` / `span` 归一化后不在**该 file_id** 的全文中 / `file_id` 不在 `docs` 中 → `fail`
- `len(span) > MAX_SPAN_LEN` → `warn`，常量从 `app/parsing/normalize.py` **import**，不得各写一个数
- **硬要求**：MUST 调用共享层 `normalize_ws`，不得私有实现。否则你的 `extracted` 判定与 Agent 4 的校验会用两套规则，
  一旦分叉，全部字段被判不合规且极难定位原因
- 新增一条建议判据（v2）：`status="missing"` 但 `notes` 不含 `not_in_source` → `warn`（占位必须说清理由）

### 3.2 银行内部政策语料 · 在 `agent-regulatory/`

```text
openspec/changes/agent-regulatory/tasks.md    1.2
```

提供 10 条内部政策摘要，由 C 负责切块与检索。
**你不写代码，只提供内容** —— 因为法规内容写错比代码写错危险得多。

---

## 4. 必读的接缝契约 + 你这一版新增的义务

```text
openspec/changes/poc-skeleton/specs/agent-contract/spec.md     ← 30 分钟，最重要
openspec/changes/poc-skeleton/design.md                       契约结构定义
design/TradeAI_需求设计_v2/Implements_doc/Orchestrator_Agent_Layer_实施设计.md  §6.2–§6.4
```

| 接缝 | 你要保证 |
|---|---|
| A → B | `value` 保留原文大小写；`source.span` 最小片段且能定位；`confirmed=false`、`edited_by_user=false`；`notes` 为 `[]` 不是 `null`；字典外字段只进 `extra_fields`；`required` 缺失有 `missing` 占位 |
| A → C | `docs[].full_text` 与原文逐字一致，不是摘要；`business_type` 只由你写 `EditState` |
| 全体 → D | 每个字段至少一条 `emit`/`transform`；每次模型调用记 `model` + `prompt_hash`；跳过记 `op="pass"` 带理由，不记 `drop` |
| **新增**：A → fixture | `fixtures/seam_a_to_b/{input.json,assert.py}`、`fixtures/seam_a_to_c/{input.json,assert.py}` 由你出，断言写成 pytest，不写金文件（`agent-contract` spec "fixture 是接缝的验收载体"） |

---

## 5. 现在能开工，但有两处前置

| 能否开工 | 说明 |
|---|---|
| ✅ `parse` 的 PDF 解析 | 可以先用裸 dict 写，等 `state.py` 落地再套 |
| ✅ `fields.yaml` 起草 | 不依赖任何代码（1.1–1.7） |
| ✅ `normalize_ws` + `MAX_SPAN_LEN` | **优先做这个**：它是全层唯一基准，C 的 `provenance_check` 等着 import 它 |
| ✅ `extract` 的 prompt 调试 | 不依赖契约（4.1） |
| ✅ `fixtures/seam_a_to_b` 骨架 | 可以按契约结构手写 `input.json` |
| ⚠️ 三分类与 `missing` 占位 | 需要 `FieldValue` / `Source` 的**字段名**（值域已冻结在 `poc-skeleton/design.md`，不必等 `app/state.py` 文件存在） |
| ⚠️ `N-` 编号 | 依赖 `app/findings.py`，该文件由你在《编排层实施设计》§6.4 的实现里落地，`poc-skeleton` 只提供 `FINDING_PREFIX` 常量 |

> `app/state.py` 文件仍未写出来（`poc-skeleton` tasks 2.1-2.4）。
> 但**字段名与语义已全部冻结在 `poc-skeleton/design.md` 第 1 节**，你不需要等文件落地就能开工 —— 只需要在 import 处留一个 TODO。

---

## 6. 还需要别人拍板的三件事（阻塞验收）

| # | 问题 | 影响 | 需谁定 |
|---|---|---|---|
| 1 | `MAX_SPAN_LEN = 200` 是否够用（长条款号、完整地址天然可能超长） | 超长即 `warn`，直接拉低 `provenance_coverage` 这个展示指标 | A + C |
| 2 | `required` 由 A **读取**（仅用于补 `missing` 占位）是否算违反"只执行 `stage=normalize`" | 若禁止，`missing` 占位无法产生，三分类第 3 个值永远缺席 | A + B |
| 3 | `business_type` 强指示词表（`见索即付` / `URDG 758` / `独立保函`）是否需要业务确认 | 判错类型会让 Agent 2/3 走错分支，且 trail 里留的是"依据充分"的假证据 | 业务方 + A |

答完这三条，把结论写回 `design.md` §14 与本文件，不要在 PR 评论里留结论。