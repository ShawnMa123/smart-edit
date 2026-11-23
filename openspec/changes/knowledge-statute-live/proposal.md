# Proposal

## Why

法规腿（`/v1/retrieve` → 豆包 compose）的代码已完整（`knowledge-statute-retrieval`、`statute-recall` 全部 task 完成），但本机 `rag=False statute=False web=off`，问 `什么是guarantee` 时**一次都没有调用过 Mercatoria**；即便打开开关，编辑器里的选中词也会把问题判成 `document_explanation`，法规腿同样不会触发。同时法规调用完全不过出站策略、运行结果无法区分"法规答的"还是"本地语料答的"、也没有不依赖隧道的契约证据 —— 因此"这次到底有没有查法规、查到了什么"目前不可自证。

先把这三件事做成可观测、可审计、可离线复现，再决定是否改查询构造（定义识别、法域策略、扩展词分档）：**查询改造的参数只能来自真实响应，不能凭猜**。

## What Changes

- **前置修正**：选中词不再劫持主题问题。`document_explanation` 只在问题指向该片段（"这段/这句/this passage…"）或问题本身没有规则/产品主题词时成立；否则按主题走 `trade_rule_explanation`，法规腿才能被触发。
- **法规调用过出站闸**：`Purpose` 增加 `statute`；调用前复用现有脱敏（金额/单号/账号/邮箱 → `[redacted]`，规则号豁免）与 40 字选中重叠拒绝；每次调用写 `egress_allowed` / `egress_blocked`（只存 query digest）。被拒绝时不发请求，层记 `blocked:<reason>` 并给出可见文案，绝不静默。
- **答案来源可区分**：`Route` 增加 `statute`，仅当答案真的引用了 `source_type="statute"` 时置位；被拒时仍为 `published`，由 statute 层的 `detail`/`hits` 说明。
- **离线契约证据**：新增一份真实 `/v1/retrieve` 原始响应 fixture 与 `httpx.MockTransport` 回放测试，在无网络、无隧道时也能断言"请求体、判定结果、引用 locator、层记录"。
- **启用与校准步骤文档化**：`SMART_EDIT_STATUTE`、`MERCATORIA_BASE_URL`、`MERCATORIA_API_TOKEN` 三个变量 + 隧道；把 `{原句 / +定义词 / +定义词+URDG} × {带法域 / 不带法域}` 的 3×2 实测结果记入 design 的 Findings，作为下一轮的依据。
- **明确不做**：`definition` 子意图、定义类不发 `jurisdictions`、扩展词分档、阈值（0.6 / `confidence=low`）调整、statute 与本地语料合并、`/v1/chat` 生成答案、compose 后二次润色。

**BREAKING**：无。默认仍关闭法规腿；关闭时行为与今天逐字节一致。

## Capabilities

### New Capabilities

- `knowledge-statute-live`: 法规腿"可启用、过出站闸、可区分来源、可离线复现"的行为 —— 何时必须尝试法规检索、调用前后各留下什么证据、被拒绝/不可用时如何表述、以及录制响应如何成为回归契约。

### Modified Capabilities

<!-- 无：`statute-retrieval`、`statute-query-expansion`、`knowledge-scope-inputs` 等能力只存在于未归档 change 中，`openspec/specs/` 下没有对应能力，无法写 MODIFIED delta。 -->

## Impact

- **后端**：`app/assistant/domain/query.py`（意图前置）、`app/assistant/egress.py`（`Purpose` + `statute` 判定）、`app/assistant/service.py`（`_run_local` 过闸与审计、`_route_for`）、`app/assistant/schemas.py`（`Route`）。
- **前端**：`web/src/api/assistantTypes.ts`（`AnswerRoute`）、`web/src/components/KnowledgePanel.tsx`（来源文案与 statute 被拒文案）。
- **数据/契约**：`fixtures/assistant/mercatoria_guarantee.json`（录制响应）、`tests/test_statute_replay.py`。
- **测试连带**：现有 `StubStatute` 用例需注入 `demo_policy()` —— 新闸生效后"没有策略"会被 fail-closed 拒绝，这是预期而非回归。
- **配置/文档**：`how_to_use.md` 增加启用与校准步骤；不新增数据库字段、无迁移。
- **对外依赖**：Mercatoria（`/v1/retrieve`）从"可选"变为"演示时必须可用"；token 与隧道由部署侧提供。