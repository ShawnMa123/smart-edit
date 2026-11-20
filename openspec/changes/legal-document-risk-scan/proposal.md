# Proposal

## Why

`legal-review` 的 `Rule check` 并没有检查编辑器里的文档：`LegalPanel` 只发三个硬编码 fact 预设，
后端跑一条合成规则 `DEMO-AMOUNT-REQUIRED`，草稿正文从未进入 legal 链路。它无法回答产品最关心的问题：
**当前这份草稿有没有法规风险、风险在哪一段、依据哪一条、哪些地方根本没查到。**

本 change 把 `Rule check` 升级为「文档风险扫描」：按条款计划 → 确定性检查 → 逐条款 RAGFlow 检索 →
豆包在给定证据内归纳 → 必要时用户可选择联网补检 → 输出带草稿锚点、覆盖率与闸门的报告。

## What Changes

- 契约：`ReviewCreate` 增加 `scope=document`（默认仍为 `question`，旧调用不变）、`draft_id`、
  `expected_revision`、`expected_content_sha256`、`business_type`、`web_search`；`Finding` 拆分
  `document_anchors`（草稿位置）与 `anchors`（法条/网页证据），新增 `suggestion`、`basis`；
  `ReviewReport` 新增 `snapshot`、`coverage_summary`、`retrieval`、`gate`；`ReviewRun` 新增 `progress`。
- 扫描：`app/legal_review/{document,checks,scan,compose,store}.py`。计划先于评估（分母 = planned）；
  必备要素 / 日期一致性 / 高风险措辞 / 占位符由确定性规则给出；每个条款一次 `/v1/retrieve`；
  豆包 `compose_json` 只能引用给定证据 id，且不能提升 severity / gate。
- 异步：`scope=document` 返回 202 + `queued`，`GET /legal/runs/{id}` 轮询；报告落 SQLite（`runs/legal.db`），
  支持 `Idempotency-Key`；`expected_revision` 不一致 → `stale_snapshot`。
- 联网：默认关闭，由用户在面板勾选（`web_search`）。结果一律 `unverified`、`human_review`，
  **永不 hard_block**；无 URL 的结果丢弃。
- 前端：`Rule check` → `Document check`：草稿 revision/sha 展示、扫描按钮、进度、覆盖率、闸门、
  按严重度排序的 findings、草稿引用块 + “Jump to clause”（编辑器定位到对应顶层 block）、
  “Draft changed since this scan” 提示、网页来源白名单样式。
- 配置：`SMART_EDIT_LEGAL_{MAX_CLAUSES,CLAUSE_CHARS,SCAN_DEADLINE,COVERAGE_RATIO,WEB_DEFAULT,MAX_WEB_CALLS,COMPOSE_TIMEOUT,MAX_EVIDENCE,DB}`。

## Capabilities

### New Capabilities

- `legal-document-risk-scan`：规定草稿扫描的计划/锚点、确定性规则、逐条款检索、证据约束综合、
  用户选择的联网补检、覆盖率与闸门，以及「未检查 ≠ 无风险」的诚实性不变量。

### Modified Capabilities

- `legal-review`：`question` scope 保留 L1 行为（同步 + `/v1/chat`）；新增 `scope=document` 的
  异步 run、报告持久化与 `GET /legal/runs/{id}`。

## Impact

- 后端：`app/legal_review/{contracts,document,checks,scan,compose,store,service}.py`、`app/api/legal.py`、
  `app/api/main.py`（注入 legal service）、`app/assistant/{gateway,egress}.py`（`compose_json`、`redact`）。
- 前端：`web/src/api/legal.ts`、`web/src/components/LegalPanel.tsx`、`AssistantPanel.test.tsx`、
  `web/src/rich/useRichEditor.ts`、`web/src/components/RichEditor.tsx`、`App.tsx`、`styles.css`。
- 测试：`tests/test_legal_document_scan.py`、`tests/test_legal_document_api.py`、`LegalPanel.test.tsx`、
  `useRichEditor.test.tsx`。
- 合规：条款文本在出站前走 `EgressPolicy.redact()`；报告记录 `retrieval.web_used/web_calls` 与每次 query，
  可回答「这次扫描是否出网、查了什么」。web 默认关，只有用户勾选才出网。