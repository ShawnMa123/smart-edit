# Design

## Context

动机见 `proposal.md` — Why。塑造本设计的仓库事实（均已核实）：

- **chat 契约**：`POST /v1/chat`（别名 `/chat`、`/v1/ask`、`/ask`）接受 `question` 或 `messages`、`retrieval_query`、`rewrite_query`、`queries[]`、`top_k`、`filters`、`answer.enabled`；返回检索结果 + `answer`、`answer_status`（`answered / partial / unsupported / unavailable / skipped / error`）、`citations[]`（chunk 级）、`references[]`（带 `cited`、`jurisdiction`、生效区间）、`coverage{unavailable, notes}`。
- **实测**：`独立保函的定义是什么` → `answered`，2 条 citations；`guarantee` + `jurisdictions=["WTO"]` → `partial`，3 条 citations；`answer.enabled=false` → `skipped`。
- **现有流水线**：`StatuteRetriever` 只发 `/v1/retrieve`；`_run_local()` 里法规调用与本地检索共用一个 **5 秒**外层 future 预算；`statute_timeout` 默认 **2.5s**、无环境变量；run deadline 默认 **120s**（`AssistantService.__init__`）。
- **两段式合成的落点**：`DoubaoGateway.compose` 目前只接收证据（`_compose_payload` 发 `id/source_type/title/source_version/excerpt`），没有 draft 字段；服务层已有 `EvidenceComposer` 作为「模型拒答」时的原文摘录兜底。
- **产品合并**：`ragflow-first-web-fallback` 让 `product_faq` 也查法规并与本地合并；`/v1/chat` 会用法律语料**直接生成答案**，对产品问题会产生误导，因此本 change 必须收窄。
- **合规边界**：chat 的生成发生在 Mercatoria 侧（服务自带 LLM），**不在**本服务的出站策略/审计范围内；本服务只能审计「问题离开本服务」的那一次请求。

## Goals / Non-Goals

**Goals:**

- 法规问题改由 `/v1/chat` 产出带引用的草稿，豆包做结构化/润色，最终仍由本服务评审与路由。
- 保留出站闸、审计、本地/联网回退与「不拒绝」策略。
- 明确超时、无结果、结构化失败三种降级路径。

**Non-Goals:**

- 不删除 `/v1/retrieve` 适配器与其离线测试（仅流水线不再调用）。
- 不做流式输出、不引入 `/v1/chat` 的多轮历史（首版只发单轮问题）。
- 不改豆包模型/提示词的既有 schema，不新增前端交互。
- 不把 chat 的 prose 当作证据（证据仍来自 `references[]` 的 chunk）。

## Decisions

### D1 · chat 只服务规则/显式范围问题；产品 FAQ 回到本地

`_should_try_statute()` 的意图集合改为 `{trade_rule_explanation}`（+ 显式声明范围）；`product_faq` 不再调用 chat，也不再把法规证据与本地合并。

- 备选：产品问题也用 chat —— 否决：chat 会在法律语料上生成答案，产品手册反而被忽略。
- 代价：显式收窄了 `ragflow-first-web-fallback` 的产品合并规则，需在 proposal/README 写明。

### D2 · 请求映射：脱敏问题 + 扩展词作为 `retrieval_query`

继续复用 `expand_terms()`：`retrieval_query = f"{screened_question} {' '.join(terms)}"`，`rewrite_query=false`，`question = screened_question`，`filters` 仍由 `build_filters(plan)` 生成。这样既保留现有召回调优（`guarantee` 靠扩展词才能命中保函条文），又不把未脱敏文本发出去。

- 备选：让 chat 自己改写 —— 否决：Mercatoria 不知道我们的扩展词表，实测裸句会漂移到 EU 合同条款。

### D3 · 响应映射：references → 证据，citations → 初始引用，status → 层 detail

- `references[]` → `EvidenceCandidate`：`citation_id = chunk_id`（稳定、可锚定），`title = source_doc`，`source_version = article_label@effective_from`，`excerpt` 由 `text` 按匹配词/句界裁剪，`locator` 带 `chunk_id/doc_id/article_label/jurisdiction/effective_from/to/score`。**无论 `answer_status` 是什么，references 都是证据**；只有 references 为空才算“无 RAG 条文”。
- `citations[]` 的 chunk_id 集合记为 `cited_ids`，用于「chat 已引用」标记；**最终引用仍以豆包答案引用的证据 id 为准**。
- `answer_status` 写入 `RetrievalLayer.detail`（`answered/partial/unsupported/unavailable/error`）；`coverage.notes` 与 `partial` 进入 limitations。
- `draft` 仅在 `answered/partial` 时可用；`unavailable/unsupported/error` 的拒答文本 MUST NOT 作为 draft（会诱导豆包复述拒答），只传证据。

### D4 · 两段式合成：draft 进入 compose payload

`DoubaoGateway.compose` 增加可选 `draft` 参数（通过 `context` 传入），`_compose_payload` 增加 `draft_answer` 字段与提示词条款：

- 只能引用给定证据 id；
- 可用 draft 的组织/措辞，但不得新增事实、不得把 draft 中的说法当作新来源；
- 必须保留 chat 的覆盖边界（`coverage`/`partial`）；
- 输出 schema 不变。

服务层在 `_compose` 中把 `chat_outcome.draft` 与 `cited_ids` 放进 `context`。若豆包不可用（未配置模型），继续用 fixture composer，但 fixture composer 不读 draft（保持现状）。

- 备选：把 draft 当额外 evidence —— 否决：draft 是 prose，不是可引用来源，会绕过评审对摘录的要求。

### D5 · 降级：无 RAG 文本走旧回退；结构化失败保留 chat 结果

- chat `unsupported/unavailable/error` 或零 chunks → `LocalOutcome.candidates` 为空、层 detail 记录状态 → 本地检索；RAG 无文本时按 `ragflow-first-web-fallback` 自动联网。
- **修正（实现后）**：只有 `references` 为空才算“无 RAG 文本”。`unavailable/unsupported/error` 但 references 非空时，仍把条文作为证据交给豆包（不传拒答文本），回答注明“法规服务自身的答案不可用”；否则会出现“Postman 里 references 有 5 条、助手却提示 RAG 无结果”的割裂。
- 豆包结构化失败/超时/拒答（现有 `MODEL_OUTPUT_INVALID`、`MODEL_REFUSED_EVIDENCE`）→ 用 `EvidenceComposer` 逐条摘录 chat 返回的 references：有 draft 时说明「草稿已生成但结构化失败」，只有证据时说明「条文证据已返回但结构化失败」；不静默丢弃。
- chat 超时 → `failed/timeout`，进入同一回退链。

### D6 · 预算：chat 独立超时，不挤占 5 秒检索预算

新增 `MERCATORIA_CHAT_TIMEOUT`（默认 60s，`AssistantSettings.chat_timeout`）；`StatuteRetriever`/chat 适配器用它作为请求超时；`_retrieve_layers()` 中本地 worker 的 future 超时从固定 5s 改为 `max(5, chat_timeout + 10)`，web worker 保持 8s。run deadline 仍为 120s；若剩余 deadline < 20s，跳过豆包润色直接用摘录兜底。

- 备选：复用 `statute_timeout=2.5s` —— 否决：chat 含生成，2.5s 必然超时。

### D7 · 审计与合规：endpoint=chat，生成侧不在本服务审计内

法规判定载荷增加 `endpoint="chat"`；允许/拒绝记录仍只存 `query_digest`。文档与审计说明：Mercatoria 侧的 LLM 调用不在本服务出站策略覆盖范围内，部署方需在语料服务侧单独审计。

### D8 · 来源标记不变

`_route_for()` 仍由最终引用推导：含 `statute` 引用 → `statute`；仅本地 → `published`；联网 → `general_web`；无引用 → `none`。chat 的 `answer_status` 不直接决定 `route`。

## Risks / Trade-offs

- [两次模型调用带来延迟与成本] → chat 独立超时 + 剩余 deadline 检查；仅在规则/范围问题发生；文档写明成本。
- [Mercatoria 的生成不在本服务出站审计内] → 审计载荷标 `endpoint=chat`，文档与部署说明要求语料服务侧审计。
- [chat 的 citations 是 chunk 级，可能与最终 claims 不一致] → 最终引用只认豆包引用的证据 id；chat citations 只作 `cited_ids` 标记。
- [产品 FAQ 收窄可能让产品问题失去法规补充] → 产品问题本来就不该用法律条文回答；本地语料仍完整。
- [chat 慢导致 run 接近 120s deadline] → 剩余 <20s 跳过润色；chat 超时回退本地/联网。
- [draft 含证据外的事实] → 提示词禁止把 draft 当来源；最终 claims 仍过 `review_answer`（摘录/实体/引用校验）。
- [chat 返回 answered 但零引用] → 按 `unsupported` 处理并回退，避免“有答案无依据”。

## Migration Plan

1. 新增 chat 适配器与映射、单测（MockTransport，离线）。
2. 切换 `_run_local()` 到 chat、调整预算/超时与产品意图；跑离线回放与 scope 测试。
3. draft 进入 compose、提示词更新、结构化失败兜底；跑 gateway/服务测试。
4. 文档与 `.env` 说明（`MERCATORIA_CHAT_TIMEOUT`）；真实服务验收 `answered/partial/unsupported/超时/润色失败`。
5. 回滚：清空 `SMART_EDIT_STATUTE`（关闭法规腿）或回退本次提交；`/v1/retrieve` 适配器仍在，可快速切回。

## Open Questions

- 是否把会话历史传给 `/v1/chat` 的 `messages`（当前不传，单轮）。
- 是否在 chat 已给出 `answered` 且豆包不可用时，直接把 chat 的 prose 作为答案（当前用证据摘录兜底）。
- 产品 FAQ 是否需要 chat 的检索能力（当前明确不用）。