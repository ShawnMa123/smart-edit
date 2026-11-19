# Tasks

## 1. 契约与确定性规则核

- [x] 1.1 `app/legal_review/contracts.py`：`ReviewCreate/ReviewRun/ReviewReport/CheckResult/Finding` 等 DTO 与枚举（对齐 v2 规格 §8.2）。验证：`tests/test_legal_review.py`
- [x] 1.2 `app/legal_review/rules.py`：受限 DSL `exists/compare` 三值逻辑。验证：单测覆盖 missing/unconfirmed/confirmed、compare 各比较符与类型不匹配
- [x] 1.3 `app/legal_review/service.py`：`run_deterministic` + `DEMO-AMOUNT-REQUIRED`。验证：金额缺失→Critical、确认→pass、未确认→unable_to_assess

## 2. 法规复用与映射

- [x] 2.1 `run_legal` 复用 `StatuteRetriever.chat_detailed()`，把 `StatuteOutcome` 映射为 `Finding/CheckResult`。验证：`tests/test_legal_review_legal.py`
- [x] 2.2 `answer_status` 闸门：`answered/partial`→Finding；`unavailable/unsupported/error`→`unable_to_assess` 且不展示无关联引用。验证：`test_unavailable_answer_is_unable_to_assess_without_surfacing_citations`、`test_partial_answer_is_a_finding_with_caveat`
- [x] 2.3 路由：`app/api/legal.py` 挂 `/legal/reviews`（202）+ `/legal/reports/{id}`，从 `app.state.assistant.statute` 复用 statute 实例。验证：TestClient 冒烟

## 3. 前端 LegalPanel

- [x] 3.1 `web/src/api/legal.ts` 客户端 + 契约类型。验证：`tsc --noEmit`
- [x] 3.2 `LegalPanel.tsx`：法规问答（建议 chip + 正文 markdown 渲染 + 引用卡片）+ 规则检查（三种事实态）。验证：`LegalPanel.test.tsx`、`AssistantPanel.test.tsx`
- [x] 3.3 `AssistantPanel.tsx` legal tab `'not-implemented'`→`'full'`；`App.tsx` 传 legal binding。验证：`AssistantPanel.test.tsx`

## 4. 诚实性验收（真实服务）

- [x] 4.1 法规问题 `银行保函的金额条款有哪些法律要求？` → `findings_present` + `qualified` + 5 引用。验证：真实 `/v1/chat` 记录
- [x] 4.2 离题问题 `天津都有什么旅游景点` → `unable_to_assess · unavailable`，不硬凑。验证：真实 `/v1/chat` 记录
- [x] 4.3 语料能部分覆盖的 `从中国进口美国牛肉都有什么法规` → `partial` finding，带覆盖边界说明。验证：真实 `/v1/chat` 记录

## 5. 回归

- [x] 5.1 `pytest tests/test_legal_review.py tests/test_legal_review_legal.py`、`npm --prefix web run typecheck`、`npm --prefix web run test`（AssistantPanel + LegalPanel）全绿
