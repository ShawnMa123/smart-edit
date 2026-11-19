# Proposal

## Why

法规/RAG 的命中目前被"低置信 / 法域未覆盖"闸门整批丢弃，模型又会因主题或法域不符直接拒答：`guarantee在wto定义是什么` 实际命中 5 条《独立保函规定》，却被判不可用并最终返回 `route=none`、零引用。用户要的是"先查知识库 → 豆包总结 → 查不到才联网"，而不是把已有命中丢掉再拒答。

## What Changes

- **RAG 必查且优先**：所有知识类问题（产品 FAQ、规则解释、显式声明法域/交易日/规则版本的问题）先调用 Mercatoria `/v1/retrieve`（RAGFlow 后端）；返回文本必须进入证据包，规则类问题仍以其为主要证据，产品类问题与本地语料合并。
- **取消"低置信/未覆盖即拒用"**：`confidence=low`、`top score<0.6`、`requested_uncovered` 不再丢弃命中，只作为答案里的限定说明；命中统一交给豆包总结。
- **不因主题/法域不符拒答**：把命中 + 覆盖边界交给豆包，要求说明"证据覆盖到什么程度"并回答可回答的部分，不允许仅因"不是某法域/某主题的官方原文"而返回零引用的拒答。
- **联网只在 RAG 无结果时自动发生**：仅当 `/v1/retrieve` 返回零条文本、调用失败或超时才走豆包联网；RAG 有任何条目时不得联网。联网继续过出站策略、写审计、标注"未核验第三方内容"。
- **两处皆空时如实说明**：明确"知识库与联网都没有找到"，不编造；这是如实说明，不是拒答。
- **BREAKING**（对外可观察）：默认会更常联网；`web_search` 开关语义从"每轮手动开启"变为"默认开启，显式关闭即不联网"；`route` 分布向 `statute` / `general_web` 偏移；法规提示由"未采用"改为"低置信，仅供参考"。
- **不改**：文档选区问题仍以选区快照为证据，不被 RAG 覆盖；Mercatoria 查询构造、扩展词表与阈值不改（阈值只降级为标注）；不新增 RAGFlow 适配器（Mercatoria 就是 RAGFlow 后端）。

## Capabilities

### New Capabilities

- `knowledge-rag-first-fallback`: 规定知识类问题的检索顺序（RAG → 豆包总结 → 联网）、命中不得因置信度/法域被丢弃、联网仅在无结果时自动发生且受出站策略约束、以及两处皆空时的如实表述。

### Modified Capabilities

<!-- 无：`openspec/specs/` 下只有 document-editor / document-import / rich-text-editing；法规、联网与出站能力只存在于未归档 change 中，无法写 MODIFIED delta。 -->

## Impact

- **后端**：`app/assistant/statute.py`（`judge()` 只标注不丢弃）、`app/assistant/service.py`（`_run_local()` 的检索顺序与回退、`_should_fallback()`/`_general_route()`、`_annotate_statute()`、`_route_for()`）、`app/assistant/gateway.py`（合成约束：不得因法域/主题拒答）。
- **前端**：`web/src/components/KnowledgePanel.tsx`（低置信"仅供参考"、联网自动回退提示、`web_search` 默认态）、`web/src/api/assistantTypes.ts`（如新增提示字段）。
- **测试**：`tests/test_statute_retrieval.py`、`tests/test_statute_replay.py`、`tests/test_assistant_general_web.py`、`tests/test_knowledge_scope.py`、`tests/test_assistant_contracts.py`、`web/src/components/KnowledgePanel.test.tsx`。
- **出站合规**：联网自动回退必须继续经过 egress 判定与审计；策略缺失时不得外发（fail-closed）。
- **文档**：`how_to_use.md` 8.1/8.2、`README.md` 的检索顺序与开关语义。