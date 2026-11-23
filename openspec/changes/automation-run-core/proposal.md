# Proposal

## Why

当前 automation 只有一个同步的 fixture proposal 接口：没有 `AutomationRun/Result`、阶段、取消、超时、`outcome`/`completion`；`review_receipt` 由 fixture 自己写成 `pass`，没有独立 Reviewer；`replace_text` 不检查金额/日期/主体等 protected facts；正文 autosave 还会把 `variables` 清空并让 `variables_version` 无意义递增。继续加 compare/extract/rewrite 之前，必须先补上这些共同地基，否则每个任务都会各自造一套临时协议。

## What Changes

- **新增 `automation-run`**：`RunCreate` / `AutomationRun` / `AutomationResult` / `OutcomeDetails`；状态 `queued|running|succeeded|failed|cancelled|timed_out`，阶段 `context|planning|processing|reviewing|publishing|done`；202 + 轮询 + 取消 + deadline；一个 run 一个不可变 result；`completion=complete|partial`；`outcome` 使用规格枚举。
- **本 change 只实现 `task_type=rewrite` 的 `replace_text` 生成**，由确定性 fixture transformer 产出 `ChangeProposal`；其他 task_type（extract/fill/define_variable/compare/compose_import/map_api/voice_command）返回明确的 `not_implemented`，不伪造成功。
- **独立 Reviewer + protected facts**：服务端提取金额/币种/日期/百分比/编号/主体/否定/义务/法律引用，比较 before/after；事实变化产生 `risk_flags`，`polish/clarify` 不得静默改事实，`replace_clause` 需 approved source refs 或显式 ack。Reviewer 生成并持久化 receipt，apply 时重验 receipt 与 proposal/context 一致；最多一次 repair。
- **依赖与过期**：新增 `automation_dependencies`，记录 draft/snapshot、variables、authorization、generator/reviewer 版本；read/apply 时重新核验，依赖变化即 stale。
- **capability 检查**：run 创建要求 `read` + `use_ai`；字段确认/编辑/应用分别走各自 capability（本 change 只实现前两者与 apply 的 lock 校验，`confirm_fields` 留给 extraction change）。
- **新增 `document-variables`**：变量值独立于正文 revision 的版本化存储；正文保存不得清空 variables 或推进 `variables_version`；变量更新使用 `If-Match: "variables-<version>"`；apply 可以同时更新正文与变量并保持原子。
- **迁移（BREAKING）**：`POST /automation/proposals` 的 fixture 创建被 `POST /automation/runs` 取代；现有 UI/tests 改为创建 run、轮询 result，再读取 `ChangeProposal`。已有 proposal/receipt 数据继续可读。
- **明确不做**：真实模型、真实 provider SDK、embedding/reranker、compare、extract/confirm、fill、variable node/occurrence UI、API mapping、voice、PostgreSQL/Worker、多用户真实身份。

## Capabilities

### New Capabilities

- `automation-run`: automation 任务的异步运行、结果、outcome/completion、取消/超时、依赖、protected facts、独立 Reviewer 与 capability 检查；本 change 只实现 `rewrite` 的确定性 `replace_text` 生成。
- `document-variables`: 变量值的版本化存储与并发语义；正文保存不触碰变量，变量更新独立版本化，apply 可原子更新正文与变量。本 change 不实现正文 variable node/occurrence。

### Modified Capabilities

<!-- 无：document-host-foundation 尚未归档，其 document-host / automation delta 还不是 durable spec；本 change 用新的 automation-run / document-variables 承载新增行为，归档后再评估是否合并。 -->

## Impact

- **新增/修改**：`app/automation/`（run schemas、service、store、operations、reviewer/facts、pipeline）、`app/documents/`（variables store/service/schemas）、`app/api/automation.py`、`app/api/documents.py`、`web/src/api/automation.ts`、`web/src/components/AutomationFixturePanel.tsx`、`web/src/App.tsx`、相关 Python/Vitest/Playwright 测试、`how_to_use.md` / `web/README.md`。
- **数据**：在 `runs/host.db` 增加 `automation_runs`、`automation_results`、`automation_dependencies`、`automation_reviews`；`document_variables`；沿用 `idempotency_records` / `outbox_events`。
- **依赖**：0 个新 Python 包；仍用 SQLite；不接真实模型。
- **兼容**：`POST /automation/proposals` 的 fixture 创建是 breaking change；apply/undo/proposal 读取接口保持兼容；旧 proposal 数据不迁移、不删除。
- **风险**：run core 容易过度设计；本 change 只允许 `rewrite`，其他 task_type 必须失败关闭；单进程 worker/超时/取消只用 local/test 语义，不能声称生产 Worker。