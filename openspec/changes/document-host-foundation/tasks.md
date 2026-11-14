# Tasks

> 依据：`proposal.md`、`specs/document-host/spec.md`、`specs/automation/spec.md`、`specs/document-editor/spec.md`、`design.md`（D1–D13）。
> 边界：只做 local/test 的 H1 宿主、autosave/Hybrid 冲突、`replace_text` 的 fixture 提案与 apply/undo；不做模型生成、compare、提取/fill、API 映射、语音、assistant automation tab、PostgreSQL/Worker。

## 1. 共享合同、投影与 anchor

- [x] 1.1 新增 `app/shared/`（Principal、AccessContext、Clock、Ids、Audit、Idempotency 的最小合同），并让 `app/assistant/ports.py` 以兼容 re-export 方式引用；`app/automation` 不得反向 import `app.assistant`。Verify: 现有 assistant 测试全绿；新增 import 边界测试断言 `app.automation.*` 不出现 `from app.assistant`。
- [x] 1.2 在 `web/src/rich/` 新增唯一 `projectDocument(rich) -> {text, blocks}`，切换 `plainText.ts` 与 `selection.ts` 使用它；`pageBreak` 不贡献字符/分隔符，块间固定 `\n\n`。Verify: `npm --prefix web run test -- src/rich` 覆盖 pageBreak、emoji、CJK、表格与列表，且 `selectionFromEditor` 的偏移与 `richToPlainText` 一致。
- [x] 1.3 新增 `app/documents/projection.py`：对 canonical text 做确定性 SHA-256、按 code point 切片、按 `node_id` 建 block map；提供与前端投影一致的 golden fixture。Verify: pytest golden 对比前端 fixture；emoji/组合字符切片不越界。
- [x] 1.4 定义 Anchor/operation 校验：`{snapshot_id,node_id,start_cp,end_cp,quote_sha256}`、非重叠、`replace_text` 必须提供 replacement；负例覆盖错位、跨节点、重叠、空范围。Verify: `tests/test_automation_operations.py` 全绿。

## 2. Host 存储、检查点与锁

- [x] 2.1 新增 `app/documents/store.py`：`schema_meta`、`documents`、`document_drafts`、`document_checkpoints`、`document_locks`、`host_audit`、`outbox_events`、`idempotency_records`；启用 WAL 与 `busy_timeout`。Verify: store 测试断言表存在、schema 版本可迁移、旧库不被更高版本打开。
- [x] 2.2 实现 draft 读取/创建/条件保存：revision 单调；相同 canonical text + variables 不推进 revision；保存成功写 checkpoint。Verify: `tests/test_document_host_store.py` 覆盖创建、单调、no-op、checkpoint 一致性。
- [x] 2.3 实现检查点不可变与恢复：旧内容恢复写新 revision，历史检查点不变。Verify: 单测断言旧 checkpoint 内容/摘要不变，新 revision 产生新 checkpoint。
- [x] 2.4 实现锁：acquire/heartbeat/release、单活动锁、lease 过期、递增 fencing token。Verify: fake clock 单测覆盖第二把锁 409、过期后新锁、旧 token 被拒。
- [x] 2.5 实现 owner/workspace 过滤与 production fail-closed：跨用户读/写统一 404；production + local adapter 启动失败。Verify: 两个 principal 的隔离测试与启动失败测试。
- [x] 2.6 实现 host 事务助手：同事务写 draft/checkpoint/回执/outbox/审计/幂等；唯一约束冲突可回滚并读回既有结果。Verify: 强制 outbox 失败时 draft 不变；重复 proposal 唯一约束测试。

## 3. Host API 与冲突语义

- [x] 3.1 `app/api/documents.py`：`POST /documents`（可选 seed 内容）、`GET /documents/{id}/drafts/{draft_id}`、`PUT /documents/{id}/drafts/{draft_id}`；返回 ETag `"draft-<revision>"`，所有数据响应 `Cache-Control: no-store`。Verify: TestClient 断言 201/200/ETag/内容摘要。
- [x] 3.2 条件写入：缺失 If-Match 返回 428；过期返回 412，body 含 `current_revision`、`content_sha256`、`conflict`，不含正文；失败不写。Verify: 先保存 rev2，再用 rev1 保存，断言 412 且 head 不变。
- [x] 3.3 锁接口：acquire/heartbeat/release；无锁或旧 token 的 save 被拒绝。Verify: TestClient 覆盖 409 lock_conflict、lease 过期、fencing 不匹配。
- [x] 3.4 错误体与请求 ID：沿用 `main.py` 的 `{error:{code,message,request_id,retryable,details?}}` 与 `X-Request-ID`，不新增第三种格式。Verify: 422/404/412 的响应结构测试。
- [x] 3.5 把 `document-host` router 挂到 `app/api/main.py`；确认 `/assistant/*` 与 `/runs/*` 行为不变。Verify: 现有 `tests/test_api.py`、`tests/test_assistant_api.py` 全绿。
- [x] 3.6 文档同步 `how_to_use.md` / `web/README.md`：说明服务端草稿、ETag、冲突和 local/test 边界。Verify: 文档中的命令/路径与 TestClient 用例一致。

## 4. Automation 提案与 apply/undo

- [x] 4.1 `app/automation/schemas.py`：Strict DTO（`ChangeProposal`、`replace_text` operation、context、preview、risk_flags、review_receipt、ProposalDecision、ApplyRequest、ApplyReceipt、ApiError）；未知字段拒绝。Verify: 契约单测覆盖合法/非法组合与枚举。
- [x] 4.2 `app/automation/store.py`：`automation_proposals`、`automation_proposal_events`、`automation_applications`；proposal 不可变、disposition 与 application_status 分离。Verify: 单测断言 accept 不改 revision，applied 只能由回执写入。
- [x] 4.3 applicability 派生：draft revision/content_sha、variables_version、authorization_version、expires_at；非 current 返回 stale/expired。Verify: 改 head/变量/授权/时间分别使提案 stale。
- [x] 4.4 operations 校验 + Reviewer gate：anchor/quote、非重叠、`review_receipt.verdict=pass`；缺失或失败一律拒绝。Verify: 负例覆盖错位、重叠、无 review、verdict=fail。
- [x] 4.5 apply 事务：`BEGIN IMMEDIATE`；条件更新 draft、写 checkpoint、消费 proposal、写 receipt/outbox/审计/幂等；任一步失败全回滚。Verify: 并发两请求只有一个成功；强制 outbox 失败时 draft/proposal 不变。
- [x] 4.6 幂等与唯一应用：同键同 body 返回原回执；同键不同 body 409；不同键同一 proposal 返回 409 `already_applied` + `existing_receipt_id`。Verify: 单测覆盖三种分支。
- [x] 4.7 undo：仅当前 head、lease/fencing 有效；写逆操作新 revision + reversal receipt；后续修改返回 `undo_conflict`。Verify: 单测覆盖成功撤销、人工编辑后冲突、二次撤销拒绝。
- [x] 4.8 fixture 提案生成器与样例：`fixtures/automation/replace_text.json`，生成 context/preview/risk/review receipt；显式标注 fixture、不接模型。Verify: `scripts/automation_demo.py` 或测试可重复生成同一 proposal_id 语义与相同 preview。
- [x] 4.9 `app/api/automation.py`：创建 fixture proposal、读取、accept/reject、apply、undo；POST 要求 `Idempotency-Key`，决策/apply/undo 要求 If-Match。Verify: TestClient 覆盖 201/200/409/412/428 与跨用户 404。
- [x] 4.10 文档同步：`how_to_use.md` / `web/README.md` 增加「fixture 提案 → 接受 → 应用 → 撤销」的最小操作与边界。Verify: 文档步骤可在 TestClient 或页面复现。

## 5. 前端 autosave 与 Hybrid 冲突

- [x] 5.1 `web/src/api/documents.ts`：GET/PUT draft、ETag/If-Match、错误映射（428/412/409）；不把 412 当网络失败。Verify: `npm --prefix web run test -- src/api/documents.test.ts`。
- [x] 5.2 `web/src/api/automation.ts`：fixture proposal 读取、accept、apply、undo、幂等键；错误映射与类型。Verify: client 单测断言 URL/方法/头/错误码。
- [x] 5.3 `App.tsx` 接入初始 draft：加载时 GET；404 时用当前内容创建；把 `draft revision` 与现有 `currentVersionId`/digest 分开显示。Verify: RTL 测试断言首次创建与重复加载。
- [x] 5.4 autosave：debounce 2s，带 If-Match；显示 saving/saved/conflict；保存成功后清 dirty；相同内容不重复请求。Verify: fake timer 测试覆盖 debounce、成功、失败、no-op。
- [x] 5.5 Hybrid 冲突：412 时编辑器内容不变，写入 `smart-edit:recovery:<doc>`，展示服务端 head digest/摘要与差异入口；提供“用服务端/保留本地并覆盖/手工合并”。Verify: 组件测试断言本地内容未丢、恢复草稿存在、服务端 head 未被覆盖。
- [x] 5.6 恢复旧版本：加载历史文本走正常 autosave 产生新 revision；历史列表不变，不直接改 checkpoint。Verify: 组件测试断言新 revision 与历史条数。
- [x] 5.7 可访问性与样式：冲突状态不只靠颜色；saving/saved/conflict 有可读文本与键盘可达动作。Verify: `npm --prefix web run test` 中的 a11y 断言 + 手工键盘检查。
- [x] 5.8 文档同步：`web/README.md` 更新 autosave/冲突/恢复草稿说明。Verify: 文档描述与组件测试一致。

## 6. 集成验收

- [x] 6.1 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`npm --prefix web run build`；确认 `/runs`、`/assistant/*`、audit/knowledge 链路未变。Verify: 命令全绿并记录测试数量。
- [x] 6.2 Playwright：新增 `web/e2e/draft.spec.ts`，覆盖首次创建 draft、autosave 成功、412 冲突保留本地内容、fixture apply/undo。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/draft.spec.ts --project=desktop`。
- [x] 6.3 手工场景验收：无锁/错用户/过期 lease/旧 token、同内容新快照、双击 apply、两键同 proposal、undo 后人工编辑、恢复旧版本。Verify: 逐条对照 specs 记录结果；未通过项不得标记完成。
- [x] 6.4 确认现有 e2e/audit/knowledge 未回归：`web/e2e/knowledge.spec.ts` 与 `web/src/e2e.audit.test.ts`。Verify: 对应命令通过。

## Workflow follow-up

- 归档前按项目评审要求确认 local/test 边界、production fail-closed 与 fixture 标注。
- H2 外部宿主、PostgreSQL/Worker、其余 operation 类型、模型生成、automation assistant tab 均为后续 change，不在本次归档范围内。
- 若首次迁移发现 localStorage 历史与初始 draft 冲突，保留旧历史并新建 draft，不删除用户本地版本。