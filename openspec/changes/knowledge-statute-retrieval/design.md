# Design

## Context

动机见 `proposal.md`。塑造本设计的既有事实（均已在仓库内核实）：

- **回退链路已存在**：`AssistantService._should_fallback()`（`service.py:517`）在「`payload.web_search` 开启 + intent 属于 trade_rule/product_faq/document_explanation + `outcome ∈ {insufficient_evidence, unable_to_assess}` + **无任何 citations** + 豆包与 web_search 可用」时返回真，随后 `_run_general_web()`（`service.py:571`）走 Ark Responses API 的 `web_search` 工具，结果标为 `source_type="general_web"` 并带 `locator.url`，再经 `apply_general_web_policy()` 丢弃不合规引用。另一条 `_general_route()`（`service.py:534`）只服务 `intent == out_of_scope` 的直达场景。
- **检索只有一个实现**：`RetrieverPort` 目前仅由 `LexicalRetriever` 实现；`_retrieve_layers` 并行跑 local 与 web，local 层 `timeout=5`。
- **合并按分数取胜**：`merge_layers` 去重后保留**较大 score**、按 `(is_web, -score)` 排序，因此不同量纲的分数不能混入。
- **Reviewer 是硬约束**：`review_answer()` 要求 `excerpt ⊆ source_text`、实体逐字出现、`claim_supported` 成立，否则删除该 claim。
- **出站统一过闸**：`egress.py` 在任何外部调用前决定 allow/redact/deny，策略缺失即拒绝；`purpose="tool_search"` 已为 web 通道准备好。
- **Mercatoria 实测**（`POST /v1/retrieve`）：`funnel 11562 → 11417 → 2`；`timings total 151ms`（rerank 118）；`confidence=medium`；`corpus.precision` = CN `exact` / US,AU,JP `degraded` / EU,INT,WTO `snapshot`；`chunks[]` 含 `chunk_id`（内容派生）、`text`（原文）、`score`（0–1）、`matched_terms`、`article_ids`、`effective_from/to`、`superseded_by`、`rank`；`diagnostics` 含 `funnel`、`zero_reason`、`confidence`、`degraded`、`timings_ms`；`field_matches.requested_uncovered` 明确列出未覆盖法域/业务类型。

## Goals / Non-Goals

**Goals:**

- 法规成为**第一个知识源**：有可用命中时只引法规原文，引用可复核（`chunk_id` → 原文 → 条号 → 生效区间）。
- **由 RAGFlow 自己的反馈决定可用性**，不可用时让既有 `_should_fallback()` 接管，不写新的升级逻辑。
- 不改 `Answer` / `RetrieverPort` / `review_answer()` 的语义；默认关闭，行为可逐字节对照。
- 三类异常（超时/重建、未覆盖、已废止）在数据结构上可区分。

**Non-Goals:**

- 不做查询改写、不做多路检索、不做跨源 RRF 融合。
- 不使用 `/v1/chat` 生成答案；不引入第二个 Composer。
- 不引入 Postgres/pgvector；不做本地语料向量化。
- 不在 Reviewer 之后做任何"润色"。

## Decisions

### D1 · 只接 `/v1/retrieve`，Composer 仍是豆包

`/v1/chat` 的增量只有 `answer` 与 `coverage`，但它的 `answer_status` / `citations[]` 与我们 `Answer` / `Citation` 不同构，且它的答案**不经过** `review_answer()`。它需要的"是否覆盖"信号，`zero_reason` + `field_matches.requested_uncovered` 已经给到。

- 备选：`/v1/chat` 且 `answer:{enabled:false}` —— 只为白拿 `coverage`，否决：多一层响应面、无新信息。

### D2 · 可用性判定放在 adapter 内；不可用就返回空，交给既有回退

这是本 change 的核心。判定输入全部来自 RAGFlow 自己的反馈：

| 信号 | 判定 | `detail` |
|---|---|---|
| `chunks == []` | 不可用 | `empty` |
| `diagnostics.zero_reason != null` | 不可用 | `zero:<reason>` |
| `requested_uncovered.jurisdictions` 非空 | 该法域未覆盖 → 不可用 | `uncovered:<J>` |
| `confidence == "low"`（**无论分数多高**） | 服务自己不确定 → 不可用 | `low_confidence` |
| `chunks[0].score < 0.6` | 弱命中 → 不可用 | `low_confidence` |
| `degraded` 含 `"embedding"` | 可用但只取 2 条 + limitation | `degraded:keyword_only` |
| `chunks[0].superseded_by != null` | 可用但 `support_level=qualified` | `superseded` |
| 其它且 `score >= 0.6` | 可用 | `ok` |

"不可用 ⇒ `return []`" 是本设计的关键简化：下游本来就把"没有候选"视为"没证据"，于是 `outcome=insufficient_evidence`、无 citations，`_should_fallback()` 自然为真。**Composer / Reviewer / 升级链路一行都不用改。**

阈值 0.35 / 0.6 是起始值，必须用 10 个真实问题校准后写进常量（实测样本 `score=1.0` / `confidence=medium`，说明分数偏高，不能凭感觉定）。

**接缝**：`RetrieverPort.search()` 只能返回列表，无处放原因。`_run_local()` 是 service 内部方法，改为返回 `(candidates, detail)`，service 再把 `detail` 写进 `RetrievalLayer`。不改 Protocol，不改 Store。

- 备选：让 adapter 抛异常表达"弱命中" —— 否决：那会被记成 `status=failed`，与"检索成功但没找到"混淆，违反"没检查 ≠ 没发现问题"。
### D3 · 新增 `source_type="statute"`，并在 UI 打徽章

法规原文与合成摘要在合规语义上必须可区分（前者可引用、有法域与生效区间）。复用 `trade_rule` 会导致徽章、冲突分层、评测口径全部失效。纯增量枚举扩展，`Answer`/`Citation` 形状不变。

### D4 · 三处正确性小修

1. **冲突只比同级来源**：`detect_conflicts()`（`domain/evidence.py:72`）改为只在同一 `source_type` 内判定（当前是"不同来源 + 不同 excerpt 即冲突"，真法规与合成摘要对 `URDG 758` 的措辞差异会稳定误报）。
2. **503 不是空结果**：Mercatoria 重建期返回 503，映射为 `RetrievalLayer(status="failed", detail="corpus_updating")`，UI 说"法规库更新中，本回答未覆盖法规"，**不显示**"没有相关规定"。
3. **已废止条文必须提示**：见 D2 表格最后两行。

- 备选：给 `statute` 更高优先级来压过冲突 —— 否决：掩盖真实冲突，且"优先级"无法在 UI 上解释。

### D5 · "人性化"只改 prompt，不加第二次调用

compose 的 system prompt 已经要求"只引用给定 evidence id、无据则返回 `insufficient_evidence`"。人性化通过 prompt 里补充语气与结构要求实现，成本为零。

**明确禁止**在 `review_answer()` **之后**再调模型润色 —— 那等于绕过引用校验，整个可信度叙事会崩；也**不建议**在之前加一次润色（改写措辞会引入原文不支持的说法，Reviewer 会删 claim，观感反而更差）。

- 可选的零风险补充：纯文本后处理（去掉多余 markdown 标记、统一标点）。

### D6 · 超时与失败语义

法规腿独立超时 **2.5s**（实测 151ms，留 16× 余量应对 rerank 抖动与弱网），失败不阻塞既有 local 层；沿用现有 per-layer 失败语义即可，不需要新的错误类型。

### D7 · `excerpt` 用 `matched_terms` 切句

用响应里的 `matched_terms[]`（中文二元组及 `start/end`）定位到包含命中词的那一句，保证 `excerpt` 是 `text` 的**精确子串**且含实体。取 `text[0:N]` 会截断句子、可能丢实体，直接触发 `excerpt_not_in_source`。

### D8 · 本 change 不使用 pgvector（显式记录）

法规检索由 Mercatoria 完成，本地语料只有 72 chunk（词法已 100%）。向量在本项目的真实位置是"本地语料扩张后的检索"与"跨源语义对齐"（需与 Mercatoria 相同的 embedding 空间：`qwen3.7-text-embedding` / dim 1024），均属后续 change。明确排除，避免"因为有数据库而迁就设计"。

## Risks / Trade-offs

- [阈值定错，把好结果判成"不可用"] → 先用 10 个真实问题校准 ±0.1 网格；单测固定一组样例分数；`detail` 落库便于回溯。
- [法规腿失败被误读成"没有相关规定"] → D4.2 的状态映射；UI 文案区分三种情况。
- [假冲突导致回答变保守] → D4.1 分层判定。
- [升级到联网后引用不可靠] → 复用既有 `apply_general_web_policy()` 与 `unverified` 标注，不新增通道。
- [法规许可与可展示长度未确认] → 首期只展示 `excerpt` + `locator`，全文按需点开 `/v1/articles/{id}`，不落库、不缓存全文。
- [明文 HTTP + Bearer token 走公网] → 本地经 SSH 隧道 `127.0.0.1:18080`，或在服务端前置网关；token 只在服务端配置。
- [Mercatoria 重建窗口不可用] → `corpus_updating` 降级 + 失败率观察（>10% 连续 5 分钟则关开关）。

## Migration Plan

1. 契约先行：`SourceType` / `RetrievalLayer.layer` / `LayerCapability` 增量扩展 + 前端类型同步（向后兼容）。
2. 默认关闭：`SMART_EDIT_STATUTE=off`，行为与今天一致；开启需同时配置 `MERCATORIA_BASE_URL` 与 token，缺失即启动失败。
3. 灰度：① 只开法规腿 → ② 打开 UI 徽章 → ③ 打开 compose prompt 调整。每步独立回滚。
4. 回滚：单个环境变量回到词法-only；无数据迁移、无 schema 变更，回滚无需清理。
5. 观察：`statute_reason` 分布、法规引用占比、p95 延迟（门槛 12s）。

## Open Questions

- 法规语料许可与**可展示摘录长度**上限 —— 影响是否允许展开全文；当前按"只展示 excerpt"处理。
- Mercatoria 重建窗口与 token 轮换责任人 —— 影响 `corpus_updating` 文案与告警阈值。
- 是否把 `/v1/articles/{id}` 的交叉引用用于"相关条款"展示 —— UI 增强，可后续追加而不改本设计。