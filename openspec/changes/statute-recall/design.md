# Design

## Context

- 法规腿在 `service._run_local` 里调用 `StatuteRetriever.search_detailed(...)`，后者用 `build_filters(plan, applicable_on)` 生成过滤条件、以**单条** `queries=[question]` 请求 `/v1/retrieve`。
- 判定在 `StatuteRetriever.judge`：`confidence=low` 一律不可用（这条是上一轮修 bug 加的，**本次不动**）。
- 现状缺口：不可用时只有 `RetrievalLayer(detail="low_confidence")`，没有命中数；`_annotate_statute` 只在"答案没有引用"时补一句，所以**本地答上时完全不提法规被拒**。
- 配置侧已有 `knowledge.sample.json`（出站预设 + 法域预设），可以自然承载术语映射。

实测（同一句 `guarantee是什么`）：

| 查询 | confidence | 命中 |
|---|---|---|
| 原句 | low | EU UCC 海关担保 ×3 |
| 原句 + `独立保函` | low | 仍以 EU 为主 |
| 原句 + `见索即付保函 独立保函 demand guarantee` | medium | 最高法 ×3（0.825/0.673/0.315） |

## Goals / Non-Goals

**Goals:**

- 通用词（`guarantee`/`保函`…）能问出**正确的法条**，而不是海关担保。
- 法规被拒时用户能知道"查过、命中了 N 条、因为低置信没采用"。
- 扩展是**数据**、确定、可审计。

**Non-Goals:**

- 不放宽 `confidence=low` 的拒绝（这是防"高分数错概念"的唯一闸）。
- 不让模型改写查询（不可审计、延迟不可控）。
- 不改法规服务的检索参数（top_k/rerank 等）。

## Decisions

### D1 · 用"原句 + 扩展术语"拼成一条查询，而不是多路

实测多路（`queries=[原句, 扩展词]`）会让 EU 海关担保与最高法条款同分并列，噪声仍在；**拼成一条查询**后服务把同义术语一起吃进 BM25 与向量，结果 3 条全部来自最高法且分数更高（0.825 vs 0.807）。

- 备选：只用扩展词（丢掉原句）—— 否决：会丢失原句里的上下文与精确标识（如"保证期间"）。
- 备选：多路查询 + `multi_query_bonus` —— 否决：服务端该参数默认 0，且噪声仍存在。

### D2 · 映射表放配置，扩展有上限

`knowledge.sample.json` 新增：

```jsonc
"query_expansion": {
  "guarantee": ["独立保函", "见索即付保函", "demand guarantee", "URDG 758"],
  "保函":       ["独立保函", "见索即付保函", "demand guarantee"],
  "escrow":     ["第三方托管", "escrow account"]
}
```

规则：大小写不敏感的**子串**命中（中文没有词边界）；每个键最多取 4 条、总计最多 12 条、扩展字符总数 ≤120；去重保序。上限存在的理由是"堆词会把查询语义糊掉"，实测超过 3–4 个术语收益迅速消失。

- 备选：模型生成扩展 —— 否决：每次提问多一次外呼、结果不可复现、无法写进 spec 的"可审计"。
- 备选：内置词表在代码里 —— 否决：刚落地的架构就是"预设是数据"，再写回代码等于回退。

### D3 · 命中数与原因一起上报

`StatuteOutcome` 增加 `hits`（服务返回的 chunks 数）与 `expansions`（本次用到的扩展词）；`RetrievalLayer` 增加可选 `hits`。前端与 `_annotate_statute` 都据此说"命中 3 条、低置信、未采用"。

- 备选：把命中数编进 `detail` 字符串（`low_confidence:3`）—— 否决：`detail` 已被多处精确匹配，改格式会让旧断言与 UI 分支失配。

### D4 · 被拒说明与"有没有引用"解耦

现在 `_annotate_statute` 只在 `not answer.citations` 时补"没有匹配到法规"。改成：只要法规层存在且不可用，就补一句（带条数与原因）；有本地引用时措辞强调"本回答基于内部来源"。

- 备选：只在低置信时加 —— 否决：零命中、未覆盖、服务重建同样需要说明，否则又回到"没查还是没找到"分不清。

### D5 · 扩展词进审计

运行审计记录 `statute_expansions`（本次展开的术语）。否则事后无法解释"为什么这次命中变了"。

## Risks / Trade-offs

- [扩展词引入噪声] → 只做"追加"不做"替换"，且上限很紧；实测该组合分数更高而非更低。
- [映射表与语料术语漂移] → 映射表是数据，可随语料更新；审计记录让漂移可见。
- [说明变多、答案变啰嗦] → 只在法规腿真正跑过时出现；产品类问题不跑法规腿，不受影响。
- [命中数与 `hits` 字段扩散到契约] → 字段可选、默认 `None`，前端按 `null` 渲染为"未测量"。

## Migration Plan

1. 配置加 `query_expansion` + 加载（含上限校验）。
2. `statute.py` 构造扩展查询、回填 `hits`/`expansions`。
3. 层记录 + 说明文案 + UI 展示。
4. 回滚：删掉配置里的 `query_expansion` 即回到"原句检索"；说明文案与 `hits` 可独立保留。

## Open Questions

- 映射表由谁维护、与语料的术语表如何同步（法务/知识负责人）。
- 是否需要按语言分别给扩展词（当前一张表混合中英文）。