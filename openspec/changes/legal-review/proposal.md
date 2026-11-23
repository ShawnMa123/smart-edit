# Proposal

## Why

`AI-Law_agent_reqirement.md`（v2）要求一个法律审查模块（`/legal/*`），把法规适用性分析落到可追溯的 `Finding/CheckResult` 上。当前仓库只有知识问答的法规腿（`/v1/chat` → 豆包结构化），没有独立的法律审查入口。本次先做最小垂直链路（L1）：复用 `/v1/chat` 链路 + 一条合成确定性规则，把 Legal tab 从「Not implemented」点亮，并守住「没检查≠没问题 / 引用可追溯 / 失败可区分」三条诚实底线。

## What Changes

- 新增 `POST /legal/reviews`（202）+ `GET /legal/reports/{id}`，同步 + 内存（异步与 PG 属 L2）。
- `modes=["deterministic"]`：走受限 DSL（当前仅 `exists/compare`）与合成规则 `DEMO-AMOUNT-REQUIRED`，金额缺失→Critical finding、确认→pass、未确认→unable_to_assess。
- `modes=["legal"]`：复用 `StatuteRetriever.chat_detailed()`（`/v1/chat`），把 `StatuteOutcome` 映射为 `Finding`（`draft`→`explanation`、`candidates`→`evidence_ids`+`anchors`、`answer_status`→`support_level`、`coverage`→`reason_codes`）。
- 前端：Legal tab `'not-implemented'`→`'full'`，新建 `LegalPanel`（法规问答 + 规则检查两个子模式，建议 + 引用卡片，正文 markdown 渲染、引用 chip 点击跳转）。
- 契约真相源：`tradeAI_requirementDesign_v2/AI-Law_agent_reqirement.md` v2；不走 main 分支 POC 的 `EditState.legal` 契约。

## Capabilities

### New Capabilities

- `legal-review`: 规定 `/legal/*` 的契约、`StatuteOutcome`→`Finding` 映射、确定性规则执行，以及「没检查≠没问题 / 引用可追溯 / 失败可区分 / answer_status 闸门」四条诚实性不变量。

### Modified Capabilities

<!-- 无：本 change 复用 `knowledge-statute-chat` 的 `/v1/chat` 适配器，不改动其契约。 -->

## Impact

- 后端：`app/legal_review/{contracts,rules,service}.py`、`app/api/legal.py`、`app/api/main.py`（挂路由）。
- 前端：`web/src/api/legal.ts`、`web/src/components/LegalPanel.tsx`、`AssistantPanel.tsx`、`App.tsx`、`styles.css`。
- 测试：`tests/test_legal_review.py`（确定性）、`tests/test_legal_review_legal.py`（映射与诚实性）、`LegalPanel.test.tsx`。
- 合规：法规生成发生在 Mercatoria 侧，本服务不新增出站调用；token 只从 `MERCATORIA_API_TOKEN` 读，不入库。
