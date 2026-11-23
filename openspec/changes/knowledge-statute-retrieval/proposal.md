# Proposal

## Why

知识助手目前只引用 72 条**合成**语料（`fixtures/knowledge/*.json`，全部 `synthetic: true`），回答里**没有任何一条真正的法律原文**；现有 33 题评测已饱和（outcome 100% / citation hit 100%），无法再证明"更可信"。

比赛提供的 Mercatoria（RAGFlow 体系的法条级检索后端，143 部法规 / 11,562 chunks，BM25 + 向量 + `gte-rerank-v2`，响应自带 `zero_reason`／`confidence`／`corpus.precision`／`superseded_by`）已经解决法规检索。缺的只是把它接成"第一个知识源"，并让**它自己的反馈**决定要不要升级到联网。

## What Changes

- **新增法规证据腿**：新增 `MercatoriaAdapter`（`RetrieverPort` 的第二个实现），调用 `POST /v1/retrieve`，把 `chunks[]` 映射成现有 `EvidenceCandidate`，`source_type` 新增 `statute`。法域与时效直接映射：`plan.jurisdictions → filters.jurisdictions`、`plan.applicable_on → filters.as_of`。
- **可用性判定放在 adapter 内部**：用响应里的 `zero_reason`、`confidence`、`score`、`requested_uncovered`、`degraded` 判定"是否可用"；不可用就 `return []`，并把原因通过 service 内部返回值写进 `RetrievalLayer.detail`。**不改 `RetrieverPort` 签名，不改 Composer / Reviewer。**
- **复用既有回退，不新增升级逻辑**：`AssistantService._should_fallback()`（`app/assistant/service.py:517`）已经实现"答案无引用且 `outcome=insufficient_evidence` → 走豆包 `web_search`（`general_web`）"。法规腿返回空时链路自动成立，本 change 只负责让它有机会被触发。
- **契约扩展（纯增量，无 BREAKING）**：`SourceType` 增加 `statute`；`RetrievalLayer.layer` 增加 `statute`；`LayerCapability` 增加 `statute` 布尔位。`Answer` / `Citation` 形状不变。
- **三处正确性小修**：①`detect_conflicts()` 只在同一 `source_type` 内判定（否则真法规与合成摘要对 `URDG 758` 的不同措辞会稳定误报冲突）；②Mercatoria 重建期的 `503` 映射为 `RetrievalLayer(status="failed", detail="corpus_updating")`，**不得**当成"0 命中"；③`superseded_by != null` 时提示"已被替代"并把 `support_level` 降为 `qualified`。
- **人性化只改 prompt**：不新增第二次模型调用（理由见 design D5）。
- **前端**：法规引用卡片 + 徽章（法域 / 生效日 / 精度 / 是否现行）+ 三类降级文案；全英文，受 `interface-language` e2e 保护。
- **评测**：新增 12–15 题小集（正例 / 负例 / 低置信 / 已废止各若干），只回答两个问题——"法规引用占比是否从 0 起来"与"负例是否不再瞎答"。

**Out of scope（明确不做）**：豆包改写查询与多路检索；跨源 RRF 融合；本地语料向量化与 PostgreSQL/pgvector；Mercatoria 的 `/v1/chat` 生成答案；compose 之后的第二次"润色"调用；改动 `review_answer()` 判定规则。

## Capabilities

### New Capabilities

- `statute-retrieval`: 从外部法规语料服务获取**可引用**的法规证据，并以其自身反馈判定可用性；不可用时让系统既有回退链路接管。含法域/时效过滤映射、引用契约映射、三类失败与降级语义。

### Modified Capabilities

<!-- 无：`knowledge-retrieval-layers` 仍归其自身 change（knowledge-assistant-web-rag），本 change 只在实现上新增一个证据源。 -->

## Impact

- **新增配置**：`MERCATORIA_BASE_URL`、`MERCATORIA_API_TOKEN`、`SMART_EDIT_STATUTE`(off|on)。默认 off；开启但缺 URL/token 时启动失败（沿用现有 fail-loudly 风格）。
- **后端代码**：`app/assistant/settings.py`（配置）、`retrieval.py`（新 adapter + 映射）、`schemas.py`（三个枚举增量）、`service.py`（`_run_local` 返回 detail、`Capabilities` 暴露 statute 实测状态）、`domain/evidence.py`（冲突分层）。
- **前端代码**：`web/src/api/assistantTypes.ts`、`web/src/components/KnowledgePanel.tsx`、`web/e2e/*`。
- **依赖**：无新增 Python 包（沿用 `httpx`）；**不引入 PostgreSQL / pgvector**。
- **外部系统**：Mercatoria（新增出站依赖，需 token）；豆包 Ark（已有，`general_web` 通道复用）。
- **测试**：新增 `tests/test_statute_retrieval.py`；扩展 `scripts/assistant_eval.py` 输出"法规引用占比"。
- **观测**：run 记录新增 `statute_reason`（`ok` / `zero:no_match` / `low_confidence` / `corpus_updating` / `uncovered:XX` / `superseded`）与引用来源分布。