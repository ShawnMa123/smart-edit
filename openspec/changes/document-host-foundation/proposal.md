# Proposal

## Why

Automation 的所有写路径（应用建议、填充、撤销）目前都没有可信的宿主：编辑器把正文和版本放在浏览器 `localStorage`，服务端只有只读快照；没有 draft revision、锁、lease/fencing、原子回执，规格 §8.2 / §16.1 明确把「缺少宿主原子条件写入」视为 M4 的上线阻塞。先把这一层补出来，后续模型生成、版本比较、字段提取才只需换生成器与 Adapter，而不必重写业务与合同。

## What Changes

- **新增 `document-host`（仅 local/test）**：服务端权威的 `documents / document_drafts / document_checkpoints / document_locks`；draft revision 单调，checkpoint 不可变；锁带 lease 与递增 fencing token；所有写入要求 `If-Match`，缺失 428、过期 412。
- **草稿自动保存**：编辑器内容变化（debounce）通过 `PUT /documents/{id}/drafts/{draft_id}` 同步；服务端以条件更新推进 revision，返回新的 ETag。人工编辑、apply、undo 都走同一个头，不再出现「服务端 rev 不动、本地继续改」的窗口。
- **Hybrid 冲突契约**：412 时客户端**不销毁本地内容**，把它保留为恢复草稿，同时展示服务端当前 head 与差异；用户可显式选择「用服务端 / 保留本地并覆盖 / 手工合并」。P0 不自动 rebase，不静默覆盖；apply/undo 遇到头变化直接拒绝（`stale_context` / `undo_conflict`）。
- **新增最小 `automation` 写入合同**：`ChangeProposal`（本 change 只实现 `replace_text`）、accept/reject、apply、undo、`ApplyReceipt`、幂等键、stale 判定与 outbox；提案由确定性 fixture/JSON 生成，不接模型。apply/undo 的正文与变量在同一个事务内更新，失败全回滚，审计/outbox 与写入同事务。
- **修改 `document-editor`**：编辑器状态从「浏览器版本是唯一来源」改为「服务端 draft 是权威、浏览器版本是本地捕获」；新增 saving / saved / conflict 状态与恢复草稿入口；恢复旧版本必须创建新的 draft revision，不覆盖历史；audit 仍针对冻结快照执行。
- **修正 anchor 与投影**：抽出唯一 `projectDocument()`（rich → text + block map），修复 `pageBreak` 造成的偏移漂移和 UTF-16 与 code point 混用；API 统一使用 code point 偏移，apply 前校验 `quote_sha256`。
- **明确不做**：模型生成、版本比较、字段提取/填充、API 映射、语音、assistant 的 automation tab、真实多用户身份、PostgreSQL、独立 Worker、外部系统发送。它们留给后续 change，本 change 只冻结宿主、冲突与 apply/undo 接缝。

## Capabilities

### New Capabilities

- `document-host`: 服务端权威的草稿、检查点、编辑锁与自动保存；条件写入、lease/fencing、Hybrid 冲突语义、恢复草稿、回执与审计边界；local/test 可用，production 必须失败关闭。
- `automation`: 不可变 `ChangeProposal` 的最小生命周期（accept/reject/apply/undo）、stale 与幂等、宿主 ApplyReceipt、正文与变量原子更新；本 change 只覆盖 `replace_text`，生成器为确定性 fixture。

### Modified Capabilities

- `document-editor`: 编辑器不再以浏览器版本为唯一权威；新增自动保存状态与 Hybrid 冲突处理，恢复旧版本必须产生新的服务端 draft revision。

## Impact

- **新增**：`app/documents/`（models、store、service、locks、projection）、`app/automation/`（schemas、service、store、domain/operations、apply/undo）、`app/api/documents.py`、`app/api/automation.py`、`tests/test_document_host_*`、`tests/test_automation_apply_*`、`web/src/api/documents.ts`、`web/src/api/automation.ts`、冲突面板与测试。
- **修改**：`app/api/main.py`（挂载 router、共享请求 ID/错误体）、`app/assistant/bootstrap.py` 或新的 `app/shared/bootstrap.py`（共享 Fake Identity/Clock/Audit/Idempotency）、`web/src/App.tsx`、`web/src/components/RichEditor.tsx`、`web/src/rich/selection.ts`、`web/src/rich/plainText.ts`、`web/src/snapshot.ts`、`web/src/styles.css`、`how_to_use.md`、`web/README.md`。
- **数据**：新增 `runs/host.db` 或同库新增 `document_*` / `automation_*` 表；沿用 `schema_meta` 版本化迁移与 `Idempotency-Key` 约定；不修改 `EditState`、`AGENT_IDS`、现有 parse/extract/normalize/audit 链路。
- **依赖**：0 个新 Python 包；SQLite 用标准库。
- **兼容与迁移**：首次打开时若服务端无 draft，从当前编辑器内容/本地最新版本创建初始 draft；已有 `localStorage` 版本继续可读，但恢复时生成新 revision；不删除旧本地历史。
- **风险**：本地宿主不是生产；单进程单 writer，不能声称多 worker/多租户安全；anchor 单位切换可能暴露既有选区测试缺口；冲突 UX 若实现不完整会退化成静默覆盖，必须用测试锁住「不丢本地内容」。