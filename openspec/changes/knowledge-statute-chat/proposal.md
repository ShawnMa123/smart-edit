# Proposal

## Why

当前法规腿只调 `/v1/retrieve` 拿 chunks，再由豆包从零组织答案；而 Mercatoria 的 `/v1/chat` 已经能返回「检索 + 生成 + chunk 级引用 + coverage」。改成 `/v1/chat` 出草稿、豆包再做结构化/润色，可以同时拿到更完整的初稿、可锚定的引用，以及我们统一的 Answer/评审/路由。

## What Changes

- **RAG 腿改调 `/v1/chat`**（`answer.enabled=true`）：流水线不再调用 `/v1/retrieve`。
- **请求沿用现有出站闸**：发送脱敏后的 `question`，把 `question + 现有扩展词` 作为 `retrieval_query`，`rewrite_query=false`；`filters` 仍来自界面法域/交易日。
- **响应映射**：`references[]` → 证据（`chunk_id`、`doc_id`、`article_label`、`jurisdiction`、生效区间、score）；`citations[]` → chat 已引用的条目标记；`answer_status` / `coverage` → 状态与限定说明。
- **两段式生成**：chat 的 `answer` 作为 draft 交给豆包，新增「结构化/润色」约束——只能引用给定证据 id、不得新增事实、必须保留覆盖边界；最终答案仍走现有评审与 `route` 推导。
- **降级**：chat 返回 `unsupported` / `unavailable` / `error` 或零 chunks → 视为无 RAG 文本 → 本地 + 联网（沿用 `ragflow-first-web-fallback` 规则）；豆包结构化失败或拒答 → 用证据原文摘录兜底并说明，不丢掉 chat 的结果。
- **产品 FAQ 不再查法规语料**：`/v1/chat` 会用法律语料回答产品问题，因此产品 FAQ 保持本地已发布语料；这是对 `ragflow-first-web-fallback` 产品合并规则的**显式收窄**。
- **超时与预算**：新增 `MERCATORIA_CHAT_TIMEOUT`（默认 60s）；法规层预算从 5s 提升到该值 + 余量；run deadline（120s）不变。
- **BREAKING**（对外可观察）：法规问题变为两次模型调用（延迟与成本上升）；引用来自 chat 的 chunk；`retrieval[statute].detail` 增加 `answer_status`；产品问题不再调用法规服务。
- **不删** `/v1/retrieve` 适配器：保留其离线回放测试，便于回滚与对比；只是流水线不再调用。

## Capabilities

### New Capabilities

- `knowledge-statute-chat`: 规定知识问答的法规腿必须用 `/v1/chat` 取「检索 + 草稿」，如何映射引用与状态、如何交给豆包结构化、无结果时如何回退，以及产品问题与出站审计的边界。

### Modified Capabilities

<!-- 无：相关能力只存在于未归档 change 中，`openspec/specs/` 下没有对应能力；本 change 显式收窄 `ragflow-first-web-fallback` 的产品合并规则。 -->

## Impact

- **后端**：`app/assistant/statute.py`（chat 适配器与映射）、`app/assistant/service.py`（`_run_local` 端点、预算、层 detail、审计）、`app/assistant/gateway.py`（draft-aware 提示词）、`app/assistant/settings.py`（`MERCATORIA_CHAT_TIMEOUT`）、`app/assistant/pipeline.py`（兜底说明）。
- **前端**：`statuteNotice()` 需要识别新状态（`answered/partial/unsupported`）；不新增交互。
- **测试**：新增 chat 适配器、服务回退、gateway draft 用例；现有 `/v1/retrieve` 适配器测试保留。
- **合规**：chat 的生成发生在 Mercatoria 侧（其自带 LLM），不在本服务的出站审计范围内；本服务仍只审计「问题离开本服务」的那一次调用，并在审计载荷写明 `endpoint="chat"`。
- **文档**：`how_to_use.md` 8.2、`README.md`、`scripts/mercatoria_chat.py` 的定位说明。