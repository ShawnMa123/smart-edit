# Proposal

## Why

知识助手目前只能基于本地已发布语料与固定文档快照作答（`LexicalRetriever` + `FixtureComposer` + 代码复核）。用户问“最新动态/最近监管口径”时，系统只能返回 `unable_to_assess` 或澄清，因为设计里明确禁止生成器拥有网络与工具（`AI_assistance_reqirement.md` §3.2）。团队现在有了豆包（Ark）API key，希望把它用在三件事上：可控联网、两层检索（联网 + 本地 RAG）、以及联网前判断问题是否在合法范围内。

难点不在“接一个 key”，而在于不能为了联网破坏三条既有承诺：**引用必须可核验、无证据不结论、客户内容不外泄**。因此本 change 把“真实模型”和“联网”都做成受约束的能力：可开关、可拦截、可审计、可降级；联网结果只能作为**补充证据**进入既有的证据包与复核管线，而不是让模型自己去搜、去总结、去断言。

## What Changes

- **真实模型网关**：新增可配置的模型提供方（豆包/Ark，OpenAI 兼容 chat completions），用于查询分析、答案撰写与（可选的）出站分类；输出 MUST 经 Pydantic schema 校验，失败即失败，不返回未校验原文；模型 MUST NOT 拥有工具、网络或写权限；本地/测试默认仍走 fixture，生产启动不得静默回退。
- **分层检索**：一次运行可组合三层证据——① 可选联网层（默认关闭、每轮显式开启、域名白名单、抓取时间与 URL 必须落库）；② 本地第二层（默认复用现有已发布语料检索，并预留内部 RAG API 适配器）；③ 文档快照层（既有选区路径）。三层统一产出 `EvidenceCandidate` 并合并为一个 `EvidenceBundle`。
- **出站闸门**：任何外呼（搜索或模型）之前 MUST 先过 `EgressPolicy`，结果只有 allow / redact / deny 三档；禁止外发文档正文、选区原文、附件内容、实体值（金额/对手方/编号）与会话身份；被拦时必须给出用户可见原因并留审计。
- **支持等级与冲突**：联网证据单独存在时答案 `support_level` 最高为 `qualified`；规则版本/生效日/适用范围仍只能由本地已发布语料支撑；本地与联网冲突时保留双方并降级，不自动裁决。
- **契约增量（向后兼容）**：`RunCreate.web_search: bool = False`；`RunStage` 增加 `screening` / `web_search` / `local_retrieval`；启用既有的 `approved_web` 来源类型并约定 `locator{url, domain, retrieved_at, provider, rank}`；联网轮次的历史消息以 `visibility="redacted"` 保存实际外发查询。
- **前端**：问答输入区提供“Search the web for the latest”开关（默认关），开启时显示“将发送/不会发送”的出站清单；回答按来源分区（Published corpus / Web / Document），网页条目显示域名、抓取时间与“未核验第三方内容”；被拦截时显示原因而不是静默失败。
- **测试与文档**：新增闸门、合并、降级、注入与“不得声称已联网核实”的用例；模型与检索均以 fixture/echo 适配器覆盖，真实 provider 由环境变量启用。

**明确不做**：外部搜索服务商的具体选型、配额与商用条款；内部 RAG 服务的真实对接（本 change 只提供端口、适配器骨架与契约测试）；法律意见或“合法合规”结论；把文档正文/选区发送给任何外部服务；模型自主工具调用、流式输出、多轮自主规划。

## Capabilities

### New Capabilities

- `knowledge-retrieval-layers`: 定义一次问答如何组合本地发布语料、可选内部 RAG 与可选联网三层证据：授权与开关、来源准入与元数据、合并与去重、支持等级上限、冲突与降级、每层状态与时间可见性。
- `knowledge-egress-policy`: 定义任何外部调用之前的出站判定：允许/脱敏/拒绝三档、禁止字段清单、失败关闭、用户可见原因、审计与脱敏存储、白名单与规则的配置化维护。
- `assistant-model-gateway`: 定义真实模型提供方的接入边界：配置启用与禁止静默回退、结构化输出校验、无工具/无网络/无写入、提供方与版本可追溯、超时与失败语义。

### Modified Capabilities

<!-- 无。agent-knowledge 的 knowledge-assistant 仍在未归档 change 中，本 change 不修改其既有要求；归档时三者并列，互不覆盖。 -->

## Impact

- **后端**：`app/assistant/ports.py`（新增 `WebSearchPort` / `RagPort` / `EgressPolicyPort` / 真实 `ModelGateway` 适配器）、`app/assistant/service.py`（阶段与闸门插入）、`app/assistant/adapters.py`（生产门槛按 provider 放行）、`app/assistant/schemas.py`（`web_search`、新阶段、`approved_web` locator 约定）、`app/assistant/pipeline.py`（分层合并与支持等级上限）、`app/knowledge/retriever.py`（作为本地第二层适配器）、`app/llm.py`（provider 解析）、`app/api/assistant.py`（透传开关）；`pyproject.toml` 增加运行时 `httpx`。
- **前端**：`web/src/components/KnowledgePanel.tsx`（开关、出站预览、来源分区、拦截提示）、`web/src/api/assistant.ts` / `assistantTypes.ts`（`web_search` 与来源标签）、`web/src/styles.css`（来源分区样式）、`web/README.md`。
- **数据**：新增审计事件 `egress_allowed` / `egress_blocked` / `web_search_failed` / `web_evidence_dropped`；消息表沿用 `visibility`；不新增存储引擎。
- **风险**：外发查询本身即披露（需默认最小化 + 白名单）；网页内容是不可信输入（prompt injection 不得提升权限）；两层检索叠加会拉长运行时间（现有 120s deadline 需要分段预算）；真实 provider 引入后 `assert_safe_mode` 的“production 一律拒绝”必须改为按 provider 白名单放行，否则生产永远起不来。

## Assumptions

以下假设在实现前需要确认，但都不改变本 change 的能力划分与任务拆分：

1. 豆包 key 视为 **OpenAI 兼容的 chat completions**；是否附带“联网插件”待确认。无论哪种，联网都由本服务的 `WebSearchPort` 显式发起，绝不交给模型自主调用工具。
2. “本地 RAG API”先按**现有 SQLite 已发布语料检索**实现第二层；内部 RAG 服务以适配器接入，本 change 提供端口、fixture 适配器与契约测试，真实端点与鉴权后续补齐。
3. 合规默认口径：只允许外发**改写后的查询文本**（可含语言/规则编号），其余一律不出站；allowed domains 与规则由配置维护，变更需留痕。