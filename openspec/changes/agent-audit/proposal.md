# Proposal: Agent 4 审计（Audit）

## Why

前三个 Agent 都会调模型，都会产出"看起来合理"的内容。发布前必须有人检查这些内容的证据链是否成立 —— 否则员工拿到一份漂亮的字段表和一份措辞稳妥的法规意见，无从判断哪一条能信。

关键在于：**这个检查必须是可判定的、可复算的、独立于生成者的。** 一个主观分数既不能在现场解释，也不能指导重跑。

## What Changes

- 新增 `app/verifier` 包：检查器注册表 + 7 个检查器
- 实现 `trail_check`：校验操作日志完整性，检出 `summarize` / `rewrite` / `drop` 三个越界操作
- 实现 `schema_check` / `conflict_check` / `coverage_check` / `citation_check`
- 接入 `provenance_check`（A 提供实现，C 提供框架）
- 产出三个可复算的可信度比率
- 实现**受控重跑**：只由 `fail` 级检查触发、携带具体失败项、有预算上限、输入类失败不重试
- `score` 字段仅展示，不参与 verdict 与重跑

**不在本 change 内**：业务对错判断、法规适用判断、LLM-as-judge 主观评分、语义蕴含（NLI）校验。

## Capabilities

### New Capabilities

- `output-verification`：检查器注册表、证据链校验、可信度比率、受控重跑

### Modified Capabilities

无。

## 与 Agent 3 拆分的原因

原 `agent-regulatory-verifier` 拆为 `agent-regulatory` 与 `agent-audit`：

- 消费者不同：`legal` 给前端与闸门，`verification` 给闸门与开发团队
- 验收标准不同：检索命中率 vs 拦截能力
- **最重要的是**：同一个 change 里，"生成侧自查（`cite_check`）"与"独立第三方校验（`citation_check`）"
  极易在实现上被合并，而合并会破坏校验的独立性 —— 生成者不能自己宣布合格

## 为什么叫 audit 而不是 verifier

- **避免与 Agent 2 的 `agent-verify` 混淆**：两者只差 4 个字母，B 极可能打开错的目录
- **不能用 `benchmark`**：在线校验与离线 benchmark 是两件事 ——
  前者在运行路径检查证据链、不判断对错；后者在开发机上有真值地判断对错。
  用 benchmark 命名 Agent 4 会直接撞上这个混淆
- "审计"准确描述其行为：检查证据链、留痕完整性、结论一致性，不做业务与法规判断

## Impact

- 新增 `app/verifier/registry.py`、`app/verifier/checkers/*`、`tests/test_verifier.py`
- 依赖 `poc-skeleton` 的 `VerificationReport` / `Issue` / `TrailEntry` / `StageReport` 契约与 `repair` 节点
- 依赖 `agent-normalize` 的 `trail` 写入约定
- `provenance_check` 由 A 实现，C 接入注册表。**理由不是"避免自审"**（三人团队无法避免 ——
  C 写的 `citation_check` / `coverage_check` / `conflict_check` 都在审 C 自己的 Agent 3），
  而是逼 A 把"什么算 `extracted`"写成可执行代码，而不是留一句含糊的口头约定
- 真正的独立性保障来自三处：检查器全是确定性代码（任何人可读判据）、离线 gold 样本有真值、
  A 的检查器接入时不许改判据
- 风险：检查器过严会压低通过率导致演示无法走到导出；需要先跑 gold 样本校准阈值
- 风险：`trail` 的完整性依赖 A/C 两边都按约定写日志，任一方漏写会让 `trail_check` 误报

## 与其他 Agent 的接缝

| 方向 | 交付物 | 对下游的承诺 |
|---|---|---|
| A / C → Agent 4 | `trail` | 每次模型调用与转换都有 `emit` / `llm_call` 记录 |
| Agent 2 / 3 → Agent 4 | `findings` / `legal` / `retrieved` | `field_keys` 非 null；每个 `chunk_id` 都在 `retrieved` 中 |
| Agent 4 → 闸门 | `verification.verdict` | 只有 `fail` 抑制发布；`warn` 不阻断但仍展示 |
| Agent 4 → 开发团队 | `eval/report.md` 中的调优建议 | 进离线报告，不进运行时 |
