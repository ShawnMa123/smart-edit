# Tasks

> 依据：`proposal.md`、`specs/automation-run/spec.md`、`specs/document-variables/spec.md`、`design.md`（D1–D12）。
> 边界：只实现 `rewrite` 的确定性 `replace_text` run；不接真实模型，不做 compare/extract/fill/mapping/voice；进程内执行器，不声称生产 Worker。

## 1. Variables 与正文解耦

- [ ] 1.1 `app/documents/schemas.py` / `store.py`：`DraftSave` 删除 `variables`；`save_draft` 不再写入或递增 `variables_json` / `variables_version`；正文保存只改 `revision` / content。Verify: 单测 `save_draft(text only)` 后 variables 与 version 不变；旧 checkpoints 仍可读。
- [ ] 1.2 新增 `PATCH /documents/{document_id}/drafts/{draft_id}/variables`：body `{variables, lock_id, fencing_token}`，`If-Match: "variables-<version>"`；缺失 428、过期 412；只递增 `variables_version`，不改 `revision`；要求 `edit` capability 与当前锁。Verify: TestClient 覆盖成功/428/412/lock_conflict/跨用户 404。
- [ ] 1.3 `HostStore` 增加 variables 更新方法与 variables checkpoint：checkpoint 同时记录 content revision、variables、variables_version；恢复旧 checkpoint 写新 revision。Verify: 单测断言两个版本独立、旧 checkpoint 不变。
- [ ] 1.4 `web/src/api/documents.ts` 的 `saveDraft` 删除 variables 字段；新增 `updateVariables`（本 change 只供测试/未来 UI）；更新 `documents.test.ts` 与 `App.draft.test.tsx`。Verify: typecheck + `npm --prefix web run test -- src/api/documents.test.ts src/App.draft.test.tsx`。

## 2. Run 合同、状态机与存储

- [ ] 2.1 `app/automation/run_schemas.py`：Strict `TaskType`、`RunCreate`、`AutomationRun`、`AutomationResult`、`OutcomeDetails`、`RunCancel`；`task_type` 枚举保留规格全集，`input` 当前只接受 `rewrite/replace_text`。Verify: 契约单测覆盖合法/非法字段与未知 task_type。
- [ ] 2.2 `app/automation/run_state.py`：纯状态机 `queued/running/succeeded/failed/cancelled/timed_out` 与 `context/planning/processing/reviewing/publishing/done`；CAS 转换、终态不可覆盖、cancel/timeout/publish 竞争。Verify: 纯函数单测覆盖所有合法/非法转换。
- [ ] 2.3 `HostStore` 新增 `automation_runs`、`automation_results`、`automation_dependencies`、`automation_reviews` 表与 repository 方法；一个 run 至多一个 result；启动时把未完成 run 标为 `failed/timed_out`。Verify: store 测试覆盖表/唯一约束/恢复/result 不可变。
- [ ] 2.4 run 创建幂等：`POST /automation/runs` 要求 `Idempotency-Key`；同键同 body 返回原 run，同键不同 body 409；幂等 claim 与 run 创建同事务。Verify: 并发/重复请求测试只产生一个 run。

## 3. Rewrite 管线、facts 与 Reviewer

- [ ] 3.1 `ContextResolver.freeze`：读取 draft、content_sha、variables_version、authorization、generator/reviewer 版本，生成 AutomationContext 与 dependencies；draft 不存在/无权返回 404。Verify: 单测覆盖依赖记录与跨用户。
- [ ] 3.2 `app/automation/pipeline.py`：把现有 `build_fixture_proposal` 迁入 fixture transformer，输出 `ChangeProposal`；只支持 `replace_text`；proposal 显式标 `fixture` / `synthetic`。Verify: 相同输入产生相同 preview/quote；未知 intent 拒绝。
- [ ] 3.3 `app/automation/facts.py`：抽取 amount/currency/percentage/date/identifier/negation/obligation/legal_reference/proper-noun，比较 quote 与 replacement，生成 risk flags；polish/clarify 事实变化拒绝，replace_clause 标记 substantive。Verify: `tests/test_automation_facts.py` 覆盖金额/日期/主体/否定/无变化/无法解析。
- [ ] 3.4 `app/automation/reviewer.py` + `automation_reviews`：服务端检查 anchor/quote/overlap/facts/context 绑定；最多一次 repair；生成 receipt 并持久化。Verify: 负例覆盖伪造 anchor、fact change、缺少 review、verdict=fail；pass 才发布 proposal。
- [ ] 3.5 `ResultPublisher`：在一个事务里写 result、proposal、dependencies、review、audit/outbox；run 状态 CAS 到 succeeded；失败全回滚。Verify: 强制 outbox 失败时 run/result/proposal 均不落盘。
- [ ] 3.6 `execute_run`：BackgroundTasks 执行 context→planning→processing→reviewing→publishing→done；deadline/cancel 检查；迟到结果不发布。Verify: fake clock 单测覆盖取消/超时/发布竞争。
- [ ] 3.7 apply 重验：`AutomationService.apply` 查 `automation_reviews`，校验 receipt 与 proposal/context 匹配；不匹配 409；`edit` capability 检查。Verify: 删除/篡改 review receipt 后 apply 被拒，draft 不变。

## 4. API、capability 与兼容迁移

- [ ] 4.1 `app/api/automation.py`：新增 `POST /automation/runs`（202 + Location）、`GET /automation/runs`、`GET /automation/runs/{id}`、`POST /automation/runs/{id}/cancel`、`GET /automation/results/{id}`；删除 `POST /automation/proposals` fixture 创建。Verify: TestClient 覆盖 202/200/404/409/412/428 与 result 合同。
- [ ] 4.2 capability 投影：Fake authorization 给 `read/use_ai/edit/confirm_fields/apply`；create/read run 要求 read+use_ai，apply 要求 edit；无能力 403，跨用户 404。Verify: 单测用没有 use_ai/edit 的 principal 覆盖拒绝路径。
- [ ] 4.3 run 错误与 ETag：cancel 使用 `If-Match: "run-<revision>"`；result 只读；`Cache-Control: no-store`；错误体沿用嵌套 `{error:{...}}`；unsupported task_type 422 `not_implemented`。Verify: 结构/headers 断言。
- [ ] 4.4 兼容迁移：保留 `GET /automation/proposals/{id}`、decision、apply、undo；更新现有测试中 `POST /automation/proposals` 的调用为 run flow。Verify: 旧 proposal/receipt 数据仍可读；apply/undo 测试全绿。
- [ ] 4.5 文档：`how_to_use.md` / `web/README.md` 更新 run/result/outcome、fixture 标注、variables PATCH、breaking endpoint；Verify: 文档命令与 TestClient 用例一致。

## 5. 前端 run 轮询与迁移

- [ ] 5.1 `web/src/api/automation.ts`：新增 run 类型与 `createRun/getRun/listRuns/cancelRun/getResult`；保留 proposal/decision/apply/undo；错误映射与幂等键。Verify: `automation.test.ts` 断言 URL/method/header/错误码。
- [ ] 5.2 `AutomationFixturePanel`：改为 create run → 轮询 → result proposal；显示 queued/running/stage/outcome/limitations；失败/取消/超时明确展示；再 accept/apply/undo。Verify: 组件测试用 fake timers 覆盖 success/needs_clarification/failure/cancel。
- [ ] 5.3 `App.tsx` / `documents.ts`：autosave 不再发送 variables；变量 PATCH 不在 UI 暴露；冲突/恢复逻辑保持。Verify: `App.draft.test.tsx` 断言 saveDraft body 无 variables；现有 412 冲突测试全绿。
- [ ] 5.4 可访问性/状态：run 的 queued/running/succeeded/failed 状态有可读文本，不仅颜色；run 面板按钮键盘可达。Verify: 组件测试 a11y 断言 + 手工键盘检查。

## 6. 集成验收

- [ ] 6.1 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`npm --prefix web run build`；确认 `/documents`、`/automation/proposals` 读取、apply/undo、audit/knowledge 未回归。Verify: 命令全绿并记录测试数量。
- [ ] 6.2 Playwright：更新 `web/e2e/draft.spec.ts` 的 fixture 流程为 create run → poll → proposal → accept/apply/undo；覆盖 queued/running 状态与 result。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/draft.spec.ts --project=desktop`。
- [ ] 6.3 AX 子集验收：同键重放、不同 body 409、取消/超时、late publish、facts change、review mismatch、variables 保存/更新、跨用户 404。Verify: 逐条对照 specs 记录结果；未通过项不得勾选。
- [ ] 6.4 现有 e2e：`web/e2e/audit.spec.ts`、`knowledge.spec.ts`、`errors.spec.ts`、`layout.spec.ts`。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- --project=desktop`。

## Workflow follow-up

- 归档前确认 `document-variables` / `automation-run` 与未归档的 `document-host` / `automation` delta 的合并策略。
- 真实模型、compare、extract/confirm、fill、API mapping、voice、Worker/PostgreSQL 均为后续 change，不在本次归档范围。
- 若变量 PATCH 发现旧客户端仍发送 variables，优先更新客户端，不做静默兼容。