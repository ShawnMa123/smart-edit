# Design

## Context

动机见 `proposal.md` — Why。塑造本设计的仓库事实（均已核实）：

- **可用性闸门会丢弃命中**：`StatuteRetriever.judge()`（`app/assistant/statute.py:187-222`）在 `confidence=low`、`top score<0.6` 或 `requested_uncovered` 非空时直接返回**无 candidates** 的结果；`_run_local()`（`service.py:981-982`）只有在 candidates 非空时才采用法规证据。因此 `guarantee在wto定义是什么` 即使命中 5 条《独立保函规定》，也被判"不可用"。
- **RAG 只覆盖部分意图**：`_should_try_statute()`（`service.py:611-617`）只在 `trade_rule_explanation` 或显式声明范围时调用；产品问题从不查法规。
- **模型被指示在证据"不匹配"时拒答**：`gateway.py:30-46` 的 `SYSTEM_PROMPT` 要求"证据只覆盖相关规则但不支持所问定义时返回 `insufficient_evidence`，不要替代问题"——这正是 `guarantee在wto定义是什么` 返回零引用拒答的直接原因。
- **联网回退条件**：`_should_fallback()`（`service.py:626-645`）要求 `payload.web_search=True`、意图在知识类、`outcome in (insufficient_evidence, unable_to_assess)` 且**没有任何引用**。因此本地语料一旦给出引用，就不会联网；RAG 被闸门拒用后若本地有引用，同样不联网。
- **联网默认值**：`settings.web_default` 未显式配置时为 `True`（`settings.py:116-119`），`Capabilities.web.default_on` 直接透传（`service.py:593`）；前端在拿到 capabilities 后按它设默认（`KnowledgePanel.tsx:300-302`），但首次渲染初始值为 `false`。
- **出站与审计已完整**：`_search_decision()` / `_general_decision()` 走 `EgressPolicy`，用途 `search` / `tool_search`，判定写审计；`general_web` 通道由 `DoubaoGateway.supports_tool_search=True`（`gateway.py:107`）提供。

## Goals / Non-Goals

**Goals:**

- 把"RAG → 豆包总结 → 无结果才联网"固化为可按层验证的确定性顺序。
- 让法规命中（含低置信/未覆盖）一定进入合成，并保留可读的覆盖边界说明。
- 让联网只发生在 RAG 无文本时，同时保留现有出站闸门与审计。

**Non-Goals:**

- 不新增 RAGFlow 适配器（Mercatoria 就是其 RAGFlow 后端），不改 `expand_terms()`、`build_filters()` 或阈值数值。
- 不改文档选区路径：存在选区且问题指向片段时仍以快照为唯一证据。
- 不在法规与本地语料之间做自动"冲突裁决"（`detect_conflicts` 行为不变）。
- 不做无限重试或多轮联网；每轮最多一次联网调用。

## Decisions

### D1 · RAG 对所有知识类意图先查；规则类独占、产品类合并

`_should_try_statute()` 扩展为：`handoff_target is None` 且意图属于 `{product_faq, trade_rule_explanation}`，或用户显式声明了法域/交易日/规则版本；`document_explanation` 且存在有效选区时不查 RAG。规则类保持"RAG 命中即独占证据"；产品类把 RAG 命中与本地语料一起放进证据包。

- 备选：所有意图一律合并 RAG 与本地 —— 否决：规则问题会被产品手册段落稀释，且现有冲突检测会把同主题的两种措辞报成冲突。
- 备选：保持只查规则问题 —— 否决：与"无论何时优先 RAG"的要求冲突。

### D2 · `judge()` 从"闸门"降级为"标注"

`judge()` 只要有 `chunks` 就返回 candidates（保留 `top_k`，`degraded` 时截断为 2 条），`reason` 继续记录 `ok / low_confidence / uncovered:* / superseded / degraded:keyword_only`。`StatuteOutcome.usable` 语义随之变为"有命中即可用"；服务层把 `reason` 转成回答里的限定说明，不再据此丢弃。

- 备选：保留闸门但增加"强制模式"参数 —— 否决：两条路径会产生两种行为，测试与文案都要分叉。
- 代价：低置信结果会出现在答案里，必须由 caveat 与 UI 徽标提示"仅供参考"。

### D3 · 合成提示词改为"说明边界并回答可回答部分"

`SYSTEM_PROMPT` 增加约束：证据列表非空时不得返回 `insufficient_evidence`；若证据只覆盖部分法域/概念，先说明覆盖边界，再给出证据能支持的内容；只有证据列表为空（或无任何引用可用）时才允许 `insufficient_evidence`。保留"只能引用给定 id、不得编造"的既有约束。

- 备选：在服务层把模型的 `insufficient_evidence` 强制改写为 `answered` —— 否决：会把没有 claim 的空答案包装成回答，破坏评审与引用一致性。
- **运行时修复（实现中发现）**：lite 模型会把说明文字写进 `outcome`（例如 `limitations_and_explanation` 或整段中文），导致 `MODEL_OUTPUT_INVALID`。`_normalise()` 只在字段“存在但非法”时按结构化字段修复（有 claims → `answered`，无 claims → `insufficient_evidence`），缺失字段仍然失败；非法重试从 1 次提高到 2 次。
- **有证据仍拒答**：模型返回 `insufficient_evidence` / `unable_to_assess` 且零引用时，先做两次语义重试（明确“证据非空不得拒答”）；仍拒绝则抛 `MODEL_REFUSED_EVIDENCE`，服务层用 `EvidenceComposer` 逐条摘录证据并标注“模型未作答、以下为原文摘录”，写审计 `model_refused_evidence`。这样“不要拒绝”由代码保证，而不只靠提示词。

### D4 · 联网触发条件改为"RAG 零文本"，与本地引用无关

`_run_local()` 返回法规层与本地层后，服务层以**证据包里是否出现 `source_type=statute`** 判断 `rag_has_text`（不依赖服务端 `hits` 字段：stub 或旧响应可能省略它）。新增回退判据：当本次**确实尝试过 RAG** 且 `rag_has_text == False`、`payload.web_search=True` 时，**无论本地是否已有引用**都调用一次 `_run_general_web()`；若联网产生引用，以联网答案为主（`route=general_web`，带未核验提示），本地引用只作为补充；若联网无引用，保留本地答案并说明"两处都未找到"。RAG 有条目但联网未发生时，`web` 摘要标 `reason="statute_answered"`，避免界面误报"服务器没有配置联网"。

- 备选：沿用"本地有引用就不联网" —— 否决：与"RAG 搜不到就开始豆包联网"的要求冲突。
- 备选：RAG 有条目但仍联网做补充 —— 否决：用户明确要求只在 RAG 无结果时联网，且会翻倍成本与时延。

### D5 · 来源标记按"实际用到的证据"分层

`_route_for()` 保持由引用推导：含 `statute` 引用 → `statute`；联网答案 → `general_web`；仅本地 → `published`；`none` 只用于确实没有任何引用。新增：RAG 命中被采用时即使 `reason=low_confidence` 也必须给出 `statute`，不得因旧的 `usable` 语义落回 `published`。

### D6 · 前端只改文案与默认态，不新增交互

- `statuteNotice()`：`low_confidence` 从"not used"改为"低置信，仅供参考"（中英各一条）；`uncovered` 文案保留。
- 联网开关：首次渲染的初始值由 `false` 改为"等待 capabilities 前不禁用"，并在拿到 `default_on` 后同步；关闭时的说明改为"关闭后本次不联网（仍会查 RAG 与本地语料）"。
- 新增一条自动回退提示：联网被自动触发时显示"RAG 未返回结果，已自动联网（未核验）"。

### D7 · 出站与审计零改动

自动联网复用 `_general_decision()`（用途 `tool_search`）或 `_search_decision()`（用途 `search`），继续写 `egress_allowed` / `egress_blocked`，保留 `policy_unavailable` fail-closed。测试只需覆盖"自动触发时也留下审计"。

## Risks / Trade-offs

- [低置信条文被当成结论] → `support_level` 最高 `qualified`，回答附"低置信，仅供参考"；UI 徽标保留 `Statute` 并可展开 locator。
- [自动联网带来的隐私/合规争议] → 仍过出站策略与脱敏、写审计；只在 RAG 零文本时发生；用户可显式关闭；文档写明默认值。
- [产品 FAQ 被法规噪声污染] → 产品意图合并而非独占；提示词要求只回答证据支持的部分；检索关键词仍来自问题本身。
- [RAG 宕机导致每轮都联网，时延与成本上升] → 层记录 `failed/<reason>`，审计可见；若需要限流，作为后续独立变更（本 change 不做）。
- [评审器仍可能丢弃全部 claim（如实体不支持）] → 保持评审；丢弃后无引用时按 D4 走联网，最终仍给用户可读结果。
- [既有测试大量断言"低置信=不可用"] → 明确列为连带修改，按新语义重写这些断言，而不是放宽断言。

## Migration Plan

1. 先改 `statute.py` 的 `judge()` 与相应单测，确认"有 chunks 即有 candidates"。
2. 再改 `service.py` 的顺序与回退（D1/D4/D5），跑离线回放与 scope 测试。
3. 改提示词（D3）与文案（D6），跑真实模型的一次可用/一次低置信验收。
4. 更新 `how_to_use.md` 8.1/8.2 与 README，写明"RAG → 总结 → 联网"的顺序、默认值、关闭方式。
5. 回滚：把 `SMART_EDIT_ASSISTANT_GENERAL_WEB=0` 或 `SMART_EDIT_ASSISTANT_WEB=off` 可立即停止联网；恢复旧检索语义需回退本次提交（无数据库迁移、无配置迁移）。

## Open Questions

- 联网结果与本地语料同时存在时的 UI 分组顺序（当前按引用来源分组，未额外排序）是否需要下一轮再优化。
- 是否给"低置信但被采用"的法规引用增加单独的视觉标记（现在只在结论旁提示）。