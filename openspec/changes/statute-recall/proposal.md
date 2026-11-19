# Proposal

## Why

问 `guarantee是什么` 时，法规腿**确实调用了** `/v1/retrieve`，但结果被判为不可用，答案来自本地合成语料。实测原始响应：

| 查询 | confidence | 命中 |
|---|---|---|
| `guarantee是什么` | **low** | EU UCC 第92条「Provision of a guarantee」（score 1.0）+ 第89/94条 |
| `什么是见索即付保函` | **medium** | 最高法《独立保函规定》第1/3/5条（score 1.0） |

原因是**术语错配**：贸易金融语境里的 `guarantee` 指"见索即付保函"，而语料里该词主要对应**海关担保**。系统按 `confidence=low` 拒绝是对的（否则会自信地引用错法条），但用户看到的是"没用法规"却不知道为什么。

实测扩展词能真正解决召回：

| 策略 | confidence | 结果 |
|---|---|---|
| 原句 | low | EU UCC ×3 |
| 原句 + `独立保函` | low | 仍以 EU 为主 |
| **原句 + `见索即付保函 独立保函 demand guarantee`** | **medium** | **最高法 ×3，score 0.825 / 0.673 / 0.315** |

## What Changes

- **术语归一化（D）**：检索前把命中的通用词替换/扩写为受控术语（配置驱动的映射表），以**单条查询**（原句 + 扩展词）发出；扩展条数与字符数有上限；实际用到的扩展词写进审计与法规层详情。
- **被拒透明化（C）**：法规层**不可用时一律说明**（不再只在"没有引用"时才说），并带上"命中 N 条但置信度低/未覆盖"的具体原因；本地语料答上了也照样说明，因为用户有权知道法规被查过而被拒。
- **层记录带命中数**：检索层新增可选字段 `hits`，让前端与回答都能说"命中 3 条但未采用"，而不是只说"没有法规"。

**Out of scope**：不放宽 `confidence=low` 的拒绝规则（那是防止"高分数错概念"的唯一闸）；不做多语种自动翻译；不改法规服务本身的检索参数；不引入模型改写（扩展词来自配置，确定性可审计）。

## Capabilities

### New Capabilities

- `statute-query-expansion`: 通用词如何被归一化为受控术语、扩展如何构造与限流、以及"法规被查过但被拒"如何向用户说明。

### Modified Capabilities

<!-- 无：`statute-retrieval` 仍只在未归档的 knowledge-statute-retrieval 中，openspec/specs/ 下没有该能力；本 change 只新增术语扩展与说明，不改其可用性判定。 -->

## Impact

- **后端**：`app/assistant/statute.py`（查询构造 + 命中数）、`app/assistant/egress.py`（配置新增 `query_expansion`）、`app/assistant/schemas.py`（`RetrievalLayer.hits`）、`app/assistant/service.py`（层记录 + 说明文案）。
- **前端**：`web/src/components/KnowledgePanel.tsx`（法规被拒时显示命中数与原因）、`web/src/api/assistantTypes.ts`（`hits`）。
- **配置**：`app/configs/knowledge.sample.json` 新增 `query_expansion` 映射表。
- **测试**：扩展构造与上限、命中数写入层、被拒说明（含本地已作答的情形）、UI 展示。
- **风险**：扩展词可能引入噪声（实测"原句 + 扩展词"优于"只扩展"）；映射表维护在数据侧，需要与语料术语保持一致。