# Proposal

## Why

豆包的 Ark API 已经可用，但当前实现走的是 `POST /chat/completions`，而实际可用的调用是 `POST /responses`（`input[]` + `stream` + `tools[]`），并且带有 `web_search` 工具。更重要的是：用户勾选“Search the web for the latest”后仍然得不到联网答案，因为

1. 运行记录显示 web 层恒为 `skipped / web_unavailable`（服务端未装配 provider）；
2. 像“今天有什么热点新闻”这类问题在 `analyze()` 里被判为 `out_of_scope`，**在检索与模型调用之前就短路**，所以即使接上豆包自带联网也不会被调用；
3. 现有规格明确“模型不具备工具、网络”，与 `web_search` 工具直接冲突。

本 change 只做两件事：把撰写网关迁到可用的 `/responses` 契约；新增一条**显式、受限、可标记**的“通用联网”通道，让范围外问题能联网作答，同时不污染规则类回答的权威性。

## What Changes

- **撰写网关迁移到 Responses API**：`POST {base}/responses`，`stream: false`，`input[]`；从响应中提取结构化 JSON 并用现有 `Answer` 模型校验；仍然**不带任何 tools**，仍然只接收问题 + 证据包。
- **新增“通用联网”通道（`general_web`）**：仅当 ① 问题被判为 `out_of_scope` 且**没有转交目标**、② 用户显式开启联网、③ 部署显式允许该通道时启用；调用豆包 `responses` 并只挂**一个只读 `web_search` 工具**（`max_keyword` 有上限、单次调用、无写、无任意 URL）。
- **新的来源与标注**：该通道的引用使用新来源类型 `general_web`，携带 `url/title/retrieved_at/annotation`；回答强制追加“通用联网、未核验第三方内容、非已发布来源”的 limitation，`support_level` 最高 `qualified`，且**绝不允许**用于规则版本、生效日、适用范围这类权威结论。
- **事后准入过滤**：工具无法在调用前限定域名，因此结果在返回后按 `egress.allowed_domains` 过滤；不在准入清单里的 URL MUST NOT 成为引用，若全部被过滤必须明说“没有可用的准入来源”。
- **转交优先级不变**：改写/审查/法规类问题（`handoff_target` 非空）MUST 继续转交，绝不走通用联网。
- **UI**：知识面板增加 `General web (n)` 引用分区与一条“general web answer — unverified”提示；开关文案说明该通道只回答范围外问题。

**不做**：B 方案（让豆包自带联网直接充当全部联网层）、两阶段证据式联网（C）、真实第三方搜索 provider、流式输出、把通用联网用于规则/合规结论。

## Capabilities

### New Capabilities

- `doubao-responses-gateway`: 定义撰写网关使用 Ark Responses API 的请求/响应契约（非流式、`input[]`、无工具）、结构化输出校验与失败语义；取代既有 chat/completions 路径（该约定的主 spec 仍在未归档的 `knowledge-assistant-web-rag` 中，归档时按顺序合并）。
- `knowledge-general-web`: 定义“通用联网”通道的准入条件、唯一只读 `web_search` 工具的使用边界、`general_web` 来源与未核验标注、支持等级封顶、事后域名过滤，以及“转交类问题不得走该通道”的硬约束。

### Modified Capabilities

<!-- 无。assistant-model-gateway / knowledge-retrieval-layers 所在 change 尚未归档，本 change 以新能力承载并在归档时合并，避免对不存在的主 spec 做 MODIFIED。 -->

## Impact

- **后端**：`app/assistant/gateway.py`（Responses 端点、请求体、响应解析、工具可选的第二个入口）、`app/assistant/schemas.py`（`SourceType` 增加 `general_web`）、`app/assistant/settings.py`（通道开关与 `max_keyword`）、`app/assistant/egress.py`（`purpose="tool_search"` 判定）、`app/assistant/service.py`（`out_of_scope` 路由与通用通道执行）、`app/assistant/pipeline.py`（通用答案的等级封顶与 limitation）。
- **前端**：`web/src/api/assistantTypes.ts`（`general_web`、annotation locator）、`web/src/components/KnowledgePanel.tsx`（分区 + 提示 + 开关文案）、样式。
- **测试/文档**：Responses 契约测试（MockTransport）、路由与优先级测试、域名过滤测试、通用答案等级/标注测试；`web/README.md`、`how_to_use.md` 更新环境变量与预期行为。
- **风险**：`web_search` 会把查询转给提供方的搜索后端（外发面变大，需要显式开关与审计）；工具结果不可在调用前限定域名；工具调用更慢，需要独立预算；**已在本轮对话中暴露的 API key 必须轮换**，仓库仍只读环境变量。