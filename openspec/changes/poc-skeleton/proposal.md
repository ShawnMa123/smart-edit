# Proposal: POC 骨架与契约冻结

> **Owner**：待认领（本 change 的头号阻塞项，见 §风险与阻塞项）· 全员 review
> **交接物**：`app/state.py`（契约）+ `app/findings.py`（编号与留痕）+ `fixtures/seam_*` 四对快照
> **上位依据**：`design/TradeAI_需求设计_v2/Requirements.md` 与
> `design/TradeAI_需求设计_v2/Implements_doc/Orchestrator_Agent_Layer_实施设计.md`

## Why

三人要并行开发四个 Agent，但没有共享状态契约时，每个人会长出不同的输入输出结构，整合日全部用来改粘合层。
更危险的是**语义分歧**：结构一样、理解不一样，编译能过、整合时全线报错。

同时，产品要求 `agent1/2/3` 可被前端单独触发（`Requirements.md` §7、§9）。这一需求把"解析"从
Agent 1 私有实现变成多人共用的基础设施 —— 若各自实现，同一份文档两次扫描会得出不同结论且无法解释。

第三个理由来自需求文档的三条硬约束："没发现问题"与"没检查"必须可区分（`StageReport`）、
"对原文的每次自由操作都要留痕"（`TrailEntry`）、"闸门不确定时默认 blocked"。
这三条**只能由编排层落地**，任何 Agent 自己实现都会变成口号。

本 change 先冻结契约与共享阶段，让后三个 change 真正并行。

## What Changes

- 定义完整 `EditState` 及全部子结构作为唯一数据契约，并**标注字段语义**：
  补齐 `SourceFile` / `Chunk`（原设计被引用却未定义）、`ParsedDoc.sha256`（docs 复用判定）、
  `Finding.confidence` / `Finding.needs_review`（可选字段，冲突降权与待人工看）
- 建立**职责矩阵**：每个 state 键只有一个写入者；`business_type` 的唯一写入者是 `normalize`
- 把 `parse` / `extract` / `normalize` 提为共享层**纯函数**并冻结签名与回执
  （`ExtractResult` 携带 `trail_entries`，由节点 `record_many()` 写回；函数本身不接收 `state`）
- 冻结**全层唯一定位基准** `normalize_ws` 与常量 `MAX_SPAN_LEN`（Agent 1 判定 `extracted`、
  Agent 4 的 `provenance_check`、Agent 2 的一致性比对全部 import 它）
- 新增共享文件 `app/findings.py`：Finding 编号（`N-` / `B-` / `R-`）+ `emit` 留痕
- 建立 LangGraph 主图（并行 join、repair 回边、gate 失败边到 `END`）
- 实现 `ingest` / `reset` / `merge` / `gate` / `export` / `hitl` / `repair` 确定性节点
- 实现 **`StageReport`**，使"检查过且无问题"与"未检查"可区分（记录追加，最新一条为准）
- 实现 **`TrailEntry`**：`summarize` / `rewrite` / `drop` 三个越界 op 一旦出现，Agent 4 必须 `fail`
- 实现**独立触发矩阵**：`parse` / `extract` / `normalize` / `agent2` / `agent3(enriched|raw)` 的自动补跑、
  上一轮产出清理、`agent4` 明确拒绝，以 `409 REFUSED` / `403 NOT_STANDALONE` 暴露
- 实现**受控重跑**：只由 `level="fail"` 的可修复检查触发，携带定位与期望，全局预算 1 次
- 实现 POC 控制平面最小集：`RunStore` + `Runner`（同一 `thread_id` 重复 resume 不得重复写库）
- 三个 Agent subgraph 以占位实现接入，保证主图当天可跑通并写出合法 `StageReport` / `TrailEntry`
- 把《实施设计》裁决的**十处设计稿不一致**回写进 design（§5），避免下次评审重吵

## Capabilities

### New Capabilities

- `orchestration`：主图编排、状态契约与职责矩阵、共享阶段、阶段状态、操作日志、独立触发、
  受控重跑、人工核对暂停、闸门判定、导出、可观测与幂等
- `agent-contract`：**接缝契约** —— 冻结边界、四个接缝的语义约定、共享层纯函数签名、
  定位基准唯一、前置声明、fixture 作为验收载体

> `agent-contract` 是独立 capability，而非 `orchestration` 的一部分。
> 原因：它约束的是**人与人之间**的交接，不是图内节点的行为。三位成员各自实现时不看主图，
> 但必须看这一份。混进 `orchestration` 会让它被当成"编排细节"而跳过。

### Modified Capabilities

无（首个 change）。

## 关键约定（八条，需三人签字）

| 约定 | 内容 | 违反后果 |
|---|---|---|
| Finding 命名空间 | `N-` / `B-` / `R-` 各自编号；`merge` 只校验前缀、排序去重，不重新编号 | 撞号即去重失效，回放无法归因 |
| 空结果两态 | `StageReport` 区分"检查过无问题"与"没检查"，下游不得混用 | 独立触发会静默返回"未发现问题" |
| 越界操作 | `summarize` / `rewrite` / `drop` 出现在日志即触发 Agent 4 `fail` | "不改事实"变成口号 |
| 分数地位 | `verification.score` 仅展示，MUST NOT 参与阻断或重跑 | 不可复算的重跑，成本失控 |
| 唯一写入者 | `business_type` 只由 `normalize` 写；`agent2` 不得写 `verification` | 谁写的查不到，Agent 4 无法判定出处 |
| 纯函数共享层 | `parse` / `extract` / `normalize` 不接收 `state`、不写日志；留痕由节点写回 | 共享层无法单测，独立触发时拿不到 `state` |
| 定位基准唯一 | `normalize_ws` / `MAX_SPAN_LEN` 只在 `app/parsing/normalize.py` 定义一次 | 两套归一化 → 全部字段被判不合规且极难定位 |
| 拒绝形态 | 前置缺失返回 `{"refused": true, "missing": [...]}` 并写 `failed` 阶段，绝不返回 `findings=[]` | 前端显示"未发现问题" |

## 不在本 change 内

四个 Agent 的真实逻辑、RAG 检索、Agent 4 的检查器集合、前端、OCR / 扫描件、表单结构还原、
真实法规库、跨单据比对（`fields` 键唯一，表达不了"发票 500,000 / 合同 480,000"，属契约级改动）。

## Impact

- 新增：`app/state.py`、`app/findings.py`、`app/stages.py`、`app/trail.py`、`app/graph.py`、
  `app/graph_factory.py`、`app/standalone.py`、`app/store.py`、`app/runner.py`、`app/parsing/*`、
  `app/nodes/*`、`app/api/main.py`、`app/storage/doc_versions.py`、`schemas/*.json`、
  `fixtures/seam_*`、`.env.example`、`pyproject.toml`
- 新增依赖：`langgraph==1.2.*`、`langgraph-checkpoint-sqlite`、`fastapi`、`uvicorn`、
  `pydantic>=2`、`pymupdf`、`pyyaml`
- 依赖本 change 的 change：`agent-normalize`（共享层、`FieldValue` / `Source`）、
  `agent-verify`（`fields` / `findings` / `business_type` / 闸门依据）、
  `agent-regulatory`（`docs` / `legal` / `retrieved` / `input_mode`）、
  `agent-audit`（`VerificationReport` / `Issue` / `TrailEntry` / `repair` 节点）
- **D1 冻结后 `state.py` 与 `parsing/` 签名不得单方面修改**；改契约 = 三人同意 +
  重跑 `pytest tests/test_contracts.py` + 更新对应 fixture

## 风险与阻塞项

| # | 项 | 影响 | 解除条件 |
|---|---|---|---|
| 1 | 本 change 无 owner | 契约无人冻结，A/B/C 无法开工 | 指定 1 人主笔（tasks §0） |
| 2 | `fields.yaml` 未定稿 | `normalize` 判不了 `extra_fields`，`fields` 键不稳定 | A 给出首批 20 个字段定义 |
| 3 | `requirements.yaml` 参数是占位值 | Agent 2 的 `blocking` 判定不可信 | 业务方给出首批业务参数 |
| 4 | `MAX_SPAN_LEN = 200` 是否够用未定 | 超长即 `warn`，拉低 `provenance_coverage` | A + C 确认后用常量统一，禁止各写一个数 |
| 5 | `escalate_to_human` 触发条件两处计数不一致（5 vs 6） | `gate` 的 `LEGAL_ESCALATED` 无法解释 | C 给出唯一清单 |

**缓解**：某人在自己 Agent 里另写一份解析 → 由 `tests/test_parsing.py`（两条调用路径 `blocks`
逐块一致）与 code review checklist 拦住；为通过演示放宽 `gate` → 由 §9 判定顺序 + 单测锁住；
`SQLite` 并发写冲突 → 进程内锁，演示机不跑并行运行。

## 验收指标

- 三人本地 `uvicorn app.api.main:app` 都能跑通全图并看到 interrupt
- `pytest tests/` 全绿，其中 `test_stages.py`、`test_gate.py`、`test_graph_flow.py` 为**每日必绿**
- 四对 fixture 互通过：A 用 B 的断言跑自己的产出，C 用 A 的 fixture 跑自己的检查器
- `langgraph dev` 能在 Studio 里看到完整图、并行分支与 interrupt