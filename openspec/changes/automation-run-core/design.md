# Design

## Context

See `proposal.md`、`specs/automation-run/spec.md`、`specs/document-variables/spec.md`。

当前实现：

- `app/automation/schemas.py` 只有 `ReplaceTextOperation`；没有 run/result/outcome。
- `app/automation/service.py::create_fixture` 同步生成 proposal；`review_receipt` 由 fixture 自己写 `pass`。
- `app/automation/operations.py::validate_operations` 只校验 anchor/quote/非空/不重叠，没有 protected facts。
- `app/documents/store.py::save_draft` 每次写入都会覆盖 `variables_json` 并把 `variables_version+1`；前端 autosave 不传变量。
- `app/documents/store.py` 有 draft/checkpoint/lock/automation 表；`host.db` 已是本地 SQLite。
- `app/api/main.py` 有 `X-Request-ID` 和嵌套错误体；automation router 目前只有 proposals/decisions/apply/undo。
- 前端 `AutomationFixturePanel` 直接调用 `/automation/proposals`，没有 run 状态。

`document-host-foundation` 尚未归档，因此本 change 不复用其 `document-host` / `automation` delta 路径，而是新增 `automation-run` 与 `document-variables` 两个 capability。

## Goals / Non-Goals

**Goals:**

- 为所有 automation 任务提供异步 run/result 骨架，并只让已实现的 `rewrite` 进入队列。
- 在发布 proposal 前做 deterministic protected facts 与服务端 Reviewer。
- 记录 run 的依赖并在 read/apply 时重验。
- 把变量从正文保存中解耦，禁止 autosave 清空变量。
- 把现有 fixture proposal UI 迁移到 run 轮询，同时保持 apply/undo 不变。

**Non-Goals:**

- 真实模型、provider SDK、embedding/reranker。
- compare、extract/confirm、fill、variable node/occurrence UI、API mapping、voice。
- 真实 Worker/租约/多进程；只用进程内执行器。
- 生产身份/多租户；仍用 Fake identity + capability 投影。

## Decisions

### D1 Run 与结果存 host.db，不新建数据库

`automation_runs / automation_results / automation_dependencies / automation_reviews` 放在现有 `runs/host.db`，与 draft/checkpoint/application 同库。原因：run 发布 proposal 与 host checkpoint 需要同事务边界；分库会引入跨库一致性问题。

替代：新建 `runs/automation.db`。会失去与 draft/apply 的原子衔接，暂不采用。

### D2 本 change 只接受 `rewrite` 的 `replace_text`

`task_type` 枚举保留规格全集，但 `create_run` 只接受 `rewrite` 且 `intent=replace_text`；其他值返回 422 `not_implemented`，不入队。这样 run 合同先稳定，又不会假装 extract/compare/map 已实现。

替代：所有 task_type 先建空 run。会制造“已支持”的假信号，不采用。

### D3 Run 状态机与发布 CAS

状态：`queued | running | succeeded | failed | cancelled | timed_out`；阶段：`context | planning | processing | reviewing | publishing | done`。

- `queued -> running` 用 CAS；
- `cancel` 只从 `queued/running` 转 `cancelled`；
- deadline 由执行器检查，转 `timed_out`；
- publish 用 `UPDATE ... WHERE status='running'`，`rowcount==1` 才写 result；
- 终态不可覆盖；迟到结果直接丢弃。

本地执行用 FastAPI `BackgroundTasks`；进程重启时把未完成 run 标为 `failed`/`timed_out`，不承诺恢复。生产 Worker 是后续 change。

### D4 Result 是不可变联合

`AutomationResult`：

```
result_id, run_id, completion, outcome, payload, limitations, created_at
```

`payload` 判别联合：

```
ChangeProposal       (outcome=proposal_ready)
OutcomeDetails       (needs_clarification / needs_handoff / unable_to_process)
```

一个 run 一个 result；result 发布后不可改。`completion=complete|partial`；本 change 的 rewrite 只允许 `complete`，因为单个变更集不能部分成功。

### D5 依赖表与 stale

`automation_dependencies(owner_type, owner_id, resource_type, resource_id, version)`。

Run 创建时记录：

```
draft / revision
draft / content_sha256
variables / variables_version
authorization / authorization_version
generator / fixture-v1
reviewer / review-v1
```

read/apply 时重新核验；任一变化返回 `stale_context`。proposal 仍保留 context 字段用于快速判断，但 dependencies 是权威记录。

### D6 Protected facts 是 deterministic checker

新增 `app/automation/facts.py`：

```
extract_tokens(text) -> FactToken[]
  amount(Decimal, currency)
  percentage
  date
  identifier
  negation / obligation
  legal_reference
  proper_noun_sequence  (保守地把连续大写词视为 party candidate)
compare(before, after) -> risk_flags[]
```

规则：

- `polish` / `clarify` 改变任一 fact → `needs_clarification`，不发布 proposal；
- `replace_clause` 改变 fact → `risk_flags += substantive_change/...`，apply 需要显式 ack；
- 没有 fact 变化 → 不产生风险；
- 所有检查失败关闭：无法解析就标 `fact_unverified`，不默认通过。

party 名称先采用保守 proper-noun 检测；未来 extraction 提供 candidate 后再替换为字段级比较。

### D7 Reviewer 是服务端步骤，receipt 绑定 proposal

新增 `app/automation/reviewer.py`：

```
Reviewer.review(draft, proposal, protected_facts, dependencies)
  -> ReviewResult { verdict: pass|repair|abstain, issues[], receipt_id, validator_version }
```

- 检查 anchor/quote、非重叠、protected facts、review receipt 的 context 绑定；
- 最多一次 repair：`repair` 后重新运行一次生成器；仍失败则 `abstain`；
- `automation_reviews` 存 receipt、proposal_id、context_hash、validator_version、issues；
- proposal 里的 `review_receipt` 只是引用；apply 必须查 `automation_reviews` 并匹配 proposal/context；
- 客户端/模型不能直接提交 `pass`。

### D8 Capability 投影

在 local/test 中由 Fake authorization 给 `Principal` 投影能力：

```
read, use_ai, confirm_fields, edit, apply
```

- `create_run` / `read result`：`read` + `use_ai`；
- `apply`：`edit` + 当前锁；
- `confirm_fields` 留给 extraction change；
- 跨用户统一 404；production 仍然 fail closed。

替代：继续只检查 owner。会让后续 extraction/guest ACL 全部返工，不采用。

### D9 Variables 与正文 revision 解耦

`document_drafts` 保留 `variables_json` / `variables_version`，但：

- `PUT /documents/{id}/drafts/{draft_id}` **不再接受 variables**；只改正文和 `revision`；
- `PATCH /documents/{id}/drafts/{draft_id}/variables` 单独更新变量，`If-Match: "variables-<version>"`，body 带锁；
- 变量更新只递增 `variables_version`，不改 `revision`；
- checkpoint 同时记录 content revision 与 variables version；
- 正文保存不再清空或推进变量。

前端 `saveDraft` 删除 variables 字段；本 change 不做变量编辑 UI，只修存储/API 语义。

替代：保留 `variables` 字段并让 `None` 表示保留。`{}` 与 `None` 仍容易混淆，且无法表达 variables 条件版本；采用独立 PATCH。

### D10 API 迁移

新增：

```
POST /automation/runs                  -> 202 + Location
GET  /automation/runs?document_id=...  -> Page
GET  /automation/runs/{run_id}
POST /automation/runs/{run_id}/cancel
GET  /automation/results/{result_id}
```

`RunCreate` 只接受 `task_type=rewrite`：

```
{
  "task_type": "rewrite",
  "document_id": "...",
  "draft_id": "...",
  "input": {
    "intent": "replace_text",
    "search_text": "USD 500,000.00",
    "replacement_text": "USD 600,000.00"
  }
}
```

**BREAKING**：删除 `POST /automation/proposals` 的 fixture 创建；现有 UI/tests 改为创建 run、轮询 result、读取 proposal。`GET /automation/proposals/{id}`、decision、apply、undo 保持不变。

### D11 错误与 ETag

- `Idempotency-Key`：所有创建 run 必填；同键同 body 返回原 run，同键不同 body 409。
- `If-Match`：run cancel 使用 `"run-<revision>"`；variables 使用 `"variables-<version>"`；proposal/apply/undo 沿用现有 `"proposal-<revision>"` / `"draft-<revision>"`。
- 错误体沿用 `{error:{code,message,request_id,retryable,...}}`；不新增第三种格式。
- `Cache-Control: no-store`。

### D12 Audit / Outbox

Run 创建/开始/取消/完成/失败、review pass/repair/abstain、result publish、proposal applied/undone 都写 `host_audit` + `outbox_events`。审计只存 ID、版本、摘要、issue code，不存完整正文、prompt 或隐式思维链。

## Risks / Trade-offs

- [Run core 过度设计] → 只实现 rewrite；其他 task_type 422；不引入 Worker/队列。
- [Protected facts 误报] → 保守地阻断/要求 ack；proper-noun 检测先标 `party_unverified`，不静默放行。
- [Reviewer 仍是确定性的] → 明确 fixture/validator 版本；不声称模型复核；未来换 Reviewer adapter 不改 apply 合同。
- [变量 PATCH 破坏旧客户端] → 更新前端/测试；旧数据继续可读；不迁移/不删除。
- [进程内 run 重启丢失] → 启动时把未完成 run 标为 failed/timed_out；生产 Worker 是独立 change。
- [两个新 capability 与现有 delta 重叠] → 归档时评估合并；本 change 不修改未归档的 `document-host` / `automation`。

## Migration Plan

1. 增加 run/review/dependency 表与 variables PATCH；保持旧数据可读。
2. 后端先启用 `/automation/runs`，把 fixture 生成改为 run。
3. 前端 `AutomationFixturePanel` 改为 create run → poll → result proposal；`saveDraft` 去掉 variables。
4. 删除 `POST /automation/proposals` fixture 创建，更新测试/文档。
5. 回滚：删除 `runs/host.db` 的 run/review 表并恢复旧 endpoint；apply/undo 数据不迁移。

## Open Questions

- proper-noun party 检测的误报率是否可接受，还是先用 `fixtures/automation/protected_terms.json` 白名单？本 change 可先保守阻断，后续 extraction 再替换。
- variables PATCH 是否需要同时支持 `expected_variables_version` body 字段（除了 If-Match）？按现有 API 习惯只用 If-Match。
- 未来 `automation` durable capability 是否合并进 `automation-run` 或改名为 `automation-write`；归档时再决定。