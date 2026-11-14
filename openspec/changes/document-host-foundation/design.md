# Design

## Context

See `proposal.md` for motivation and `specs/document-host/spec.md` / `specs/automation/spec.md` for behavior.

当前实现的关键约束：

- `web/src/versionStore.ts` 的版本历史是 browser-local；`web/src/App.tsx` 的正文只在 React state，服务端没有 draft。
- `app/assistant/store.py` 已有 `BEGIN IMMEDIATE` + 条件更新 + 同事务写消息/终态/审计的先例；`assistant_snapshots` 只有 `text + sha256`，没有 rich structure。
- `app/api/main.py` 已有 `X-Request-ID` 中间件和 `Idempotency-Key` 读取，但**没有任何 ETag / If-Match**。
- `app/runs.py::RunStore` 是进程内字典，不能作为持久文档来源。
- `web/src/rich/plainText.ts` 与 `web/src/rich/selection.ts` 是两套投影；`pageBreak` 在 selection 中多加 2 个字符，且 JS UTF-16 与 Python code point 混用，会让 `ANCHOR_MISMATCH`。
- `app/assistant/adapters.py` 的 local/fake + production fail-closed 模式可以复用，但 automation 不应反向 import assistant。

## Goals / Non-Goals

**Goals:**

- 用本地服务端宿主把 draft revision、检查点、锁/lease/fencing、条件写入和回执变成可校验事实。
- 冻结一套 anchor/投影语义，使 autosave、apply、undo、audit 使用同一份文本偏移。
- 用 `replace_text` 一条最小垂直链路验证 apply/undo 的事务、幂等、stale 与冲突语义。
- 保持 local/test 可用、production 失败关闭；不把本地宿主伪装成生产文档服务。

**Non-Goals:**

- 不做模型生成、compare、字段提取/填充、API 映射、语音、assistant automation tab。
- 不做 PostgreSQL、独立 Worker、多租户、CRDT、多人实时合并。
- 不做自动 rebase、自动合并或任何“本地预览即已保存”的行为。

## Decisions

### D1 宿主权威放在本地服务端，而不是浏览器

采用 H1：`document_drafts` 是唯一权威，浏览器只持有未保存内容与恢复草稿。理由：apply/undo 的互斥、幂等、撤销冲突都要求服务端能判断“当前头”；浏览器 localStorage 无法提供可校验的 revision，也无法阻止第二个标签页覆盖。

替代方案：

- H0 浏览器宿主：只能 proposal-only，无法满足本 change 的 apply/undo 合同。
- H2 外部宿主：生产正确，但当前没有可接入的文档服务，无法先冻结合同与测试。

H1 只在 local/test 启用；production 启动时若仍配置本地 adapter，必须失败关闭。

### D2 定义 `DocumentHostPort`，H1 只是一个 adapter

`application` 层只依赖 port：

```text
freeze(principal, document_id) -> DocumentContext
read_draft(principal, draft_id) -> DraftView
save_draft(principal, draft_id, expected_revision, content, variables) -> DraftView
acquire_lock / heartbeat / release
apply(principal, proposal, preconditions) -> ApplyReceipt
undo(principal, receipt_id, preconditions) -> ApplyReceipt
```

这样后续 H2 只替换 adapter，automation service、proposal 校验与测试不变。port 不暴露 SQL，也不让 domain 依赖 FastAPI。

### D3 单一投影、code point 偏移、snapshot 内结构路径

新增唯一投影：

```text
projectDocument(rich) -> { text, blocks: [{node_id, start_cp, end_cp, node_sha256}] }
```

规则：

- `pageBreak` 不贡献字符，也不贡献分隔符；块之间固定 `\n\n`。
- API/DTO 的 offset 一律是 Unicode code point；客户端负责 UTF-16 → code point 转换。
- `node_id` 是 snapshot 内的结构路径（如 `b3.r1.c2`），不承诺跨快照稳定；跨快照对齐属于 compare 的职责。
- `quote_sha256` 对规范化后的原文切片计算；apply 前必须重算并匹配。

替代方案：继续用两套投影 + 行号 anchor。已被 pageBreak/emoji 的失配证明不可靠。

### D4 revision 单调、相同内容不推进

- 每次接受的正文或变量变化：`revision += 1`，同时写 checkpoint。
- 相同 canonical text + 相同 variables：返回当前 head，不新增 revision/checkpoint。
- 所有写入必须带 `If-Match: "draft-<revision>"`；缺失 428，过期 412。
- 412 响应返回 `current_revision`、`content_sha256`、`conflict` 代码和当前 head 的可读摘要；不返回完整正文（避免越权/泄漏）。

替代方案：把 revision 绑定到时间戳或内容哈希。时间戳不能表达“基于哪个版本”；纯哈希无法区分“相同内容的两次保存”，也无法做乐观锁。

### D5 锁：单活动锁 + lease + 递增 fencing

- 获取锁时生成 `lock_id` 和递增 `fencing_token`，lease 默认 30s，心跳 10s。
- 同一 draft 只允许一个未释放锁；第二个请求 409 `lock_conflict`。
- apply/undo/save 校验：lock owner、lease 未过期、fencing token 相等。
- lease 过期后允许新锁获取并递增 token；旧 token 的请求一律拒绝。

替代方案：只用 owner 字段、不设 lease。进程崩溃/断网后锁永远不释放，且无法防止旧客户端重放。

### D6 Hybrid 冲突契约

服务端只返回冲突事实，不做合并：

```text
client PUT If-Match "draft-13"
server 412 {code: "stale_draft", current_revision: 14, content_sha256: "..."}
```

客户端行为：

1. 保留本地内容在编辑器与恢复草稿中（`localStorage`，明确标注“未保存到服务端”）。
2. 展示服务端 head 的摘要/差异入口；不自动替换编辑器。
3. 提供显式动作：用服务端 head、保留本地并覆盖（需要新的 If-Match 与确认）、或手工合并后保存。
4. apply/undo 遇到 412/409 直接拒绝，提示基于新 head 重新生成；不自动 rebase。

替代方案：服务端 last-write-wins。会静默吞掉另一端的内容，违反 specs。

### D7 Apply 事务顺序

事务外：加载 proposal/授权/依赖 → 派生 applicability → 校验 disposition/risk → 读 draft/lock → 校验 operations（anchor、quote、重叠、变量）→ 纯函数计算 new_content/new_variables。

事务内（`BEGIN IMMEDIATE`）：

1. 重读 draft，确认 revision/content_sha/variables_version 未变；
2. 条件 `UPDATE document_drafts ... WHERE revision=? AND text_sha256=?`，`rowcount==1`；
3. `INSERT document_checkpoints`；
4. 条件更新 proposal 为 applied，`rowcount==1`；
5. `INSERT automation_applications`（`UNIQUE(proposal_id)`）；
6. `INSERT outbox_events` + 审计；
7. `INSERT idempotency_records`；
8. `COMMIT`；任一步失败 `ROLLBACK`。

模型/复杂计算不得在事务内执行。

替代方案：先改正文、再异步写回执/审计。崩溃会出现“已改但无回执”，违反 specs。

### D8 幂等与“每个提案至多应用一次”

- 所有 POST 要求 `Idempotency-Key`（8–128 字符），scope 为 principal + method + path。
- 同键同 body：返回原响应；同键不同 body：409 `idempotency_conflict`。
- `automation_applications.proposal_id` 唯一：不同键应用同一 proposal，第二次返回 409 `already_applied` + `existing_receipt_id`。
- 幂等记录在 apply 的同一事务内写入；唯一约束冲突时回滚并读取既有记录，避免“先 get 再 put”的竞态。

替代方案：沿用 assistant 的 `_idempotent()`。它没有原子 claim，两个并发请求会重复执行。

### D9 Undo 只撤销当前头

- 仅允许撤销“最近一次成功且 `draft.revision == receipt.new_revision`”的 automation 应用。
- 逆操作在 apply 时固化为 `inverse_operations_json`，不在 undo 时重新推理。
- undo 写新 revision + 新 checkpoint + reversal receipt；保留原 receipt 和所有历史。
- 后续人工编辑/另一 automation 应用推进 head → 409 `undo_conflict`，不覆盖。

替代方案：允许撤销任意历史 receipt。需要三方合并或 rebase，超出 P0，且会与后续修改冲突。

### D10 最小 ChangeProposal：只做 replace_text + fixture 生成

本 change 只实现 `replace_text`：

```text
operation = {
  op: "replace_text",
  anchor: {snapshot_id, node_id, start_cp, end_cp, quote_sha256},
  replacement_text: string
}
```

提案必须带 `context`（document_id、draft_id、revision、content_sha256、variables_version）、`preview`（before/after、hunk）、`risk_flags`、`review_receipt.verdict=pass` 和 `expires_at`。生成器是 fixture/确定性 JSON，不接模型；模型接入留给后续 change。

替代方案：一次实现全部 operation 类型。会让事务、变量、块结构同时变复杂，难以先冻结合同。

### D11 存储：独立 host 库，独立 schema 版本

使用 `runs/host.db`（或 `SMART_EDIT_HOST_DB`），与 `assistant.db` 分开：

```text
documents
document_drafts
document_checkpoints
document_locks
automation_proposals
automation_proposal_events
automation_applications
host_audit / outbox_events
idempotency_records
schema_meta
```

理由：automation 不应再扩 `assistant/store.py`；分开库便于回滚（删除 host.db 不影响知识库）。代价是将来要统一审计/身份时需要迁移；在 `DocumentHostPort` 后替换 adapter 即可。

SQLite 并发：`PRAGMA journal_mode=WAL`、`busy_timeout=5000`、`BEGIN IMMEDIATE`；只承诺单进程单 writer。

### D12 HTTP 约定与错误体

- 路径：`/documents/*`、`/automation/*`（沿用仓库无 `/api/v1` 前缀的习惯，偏差写入文档）。
- ETag：`"draft-<revision>"`、`"proposal-<revision>"`；If-Match 缺失 428，过期 412。
- 复用 `main.py` 的 `X-Request-ID` 中间件；错误体沿用 assistant 的嵌套 `{error: {code, message, request_id, retryable, details?}}`，不新增第三种格式。
- 所有数据响应 `Cache-Control: no-store`。

替代方案：按规格用扁平 `{code, message, request_id}`。会与现有 assistant 客户端/错误处理分叉；先在 design 记录偏差，后续可统一。

### D13 前端接入与 localStorage 迁移

- 首次加载：`GET /documents/{id}/drafts/{draft_id}`；若 404，则用当前编辑器内容（或最新本地版本）创建初始 draft，并显示“已创建服务端草稿”。
- 自动保存：debounce 2s，带 `If-Match`；`saving/saved/conflict` 状态与现有 dirty 标记合并，不显示两个互相矛盾的“已保存”。
- 冲突：保留本地内容为 `smart-edit:recovery:<doc>`，展示服务端 head 的 digest/摘要与“查看差异”入口；不自动替换编辑器。
- 恢复旧版本：把历史文本作为本地编辑，然后通过正常 autosave 写为新 revision；不直接改历史。
- audit 仍用冻结快照；`Run spec audit` 提交的是当前已保存 head 或显式捕获的 snapshot，二者必须在 UI 上区分。

## Risks / Trade-offs

- [本地宿主被误当成生产] → production 启动失败关闭；UI/文档明确标注 local/test；不提供外部网络接口。
- [anchor 单位切换暴露旧选区缺陷] → 先加 pageBreak/emoji/CJK 测试，再改 apply；服务端始终重算 quote hash，失败关闭。
- [autosave 冲突 UX 退化成静默覆盖] → 用测试锁住“412 时编辑器内容不变、恢复草稿存在、服务端 head 不被覆盖”。
- [单进程 SQLite 被多 worker 破坏] → 只支持单进程；文档写明；后续 PostgreSQL/Worker 是独立 change。
- [幂等记录与业务写入不一致] → 同一事务写幂等记录；唯一约束冲突时回滚并返回既有结果。
- [proposal 生成仍可能不诚实] → fixture 必须显式标注；review receipt 缺失/非 pass 一律拒绝 apply。
- [恢复旧版本绕过审批/审计] → 恢复只产生新 draft；审批/导出/交接仍走各自的最终快照检查和 gate，不复用旧审计。

## Migration Plan

1. 新增 host 库与表；不动 `assistant.db`。
2. 后端先启用 `GET/PUT draft` 与 `/documents/*`；旧客户端不调用时保持现有 localStorage 行为。
3. 前端切到 autosave：首次加载创建初始 draft；保留 localStorage 历史与恢复草稿。
4. 启用 `/automation/proposals`（fixture）与 apply/undo；先只在 local/test。
5. 回滚：前端可通过配置关闭 autosave 回到纯 local；删除 `runs/host.db` 回到初始状态；不迁移/不删除 `assistant.db`。

## Open Questions

- 恢复草稿的保留期限与清理策略（localStorage vs 服务端恢复草稿）——不改变本 change 的 specs，可在实现时按现有 `MAX_VERSIONS` 习惯处理。
- 未来 H2 外部宿主是否需要保留 `document_id/draft_id` 同一命名——由接入方合同决定，port 已隔离。
- 是否把 `assistant_snapshots` 与 host checkpoints 合并——留给后续统一快照 change，本 change 不合并。