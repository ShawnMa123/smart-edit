# Proposal: Agent 3 法规合规

## Why

前两个 Agent 只保证"格式对、材料齐"，但审批还需要"能不能做、要加什么条件"。这项判断必须依据可追溯的法规与政策原文，因此需要检索增强。

关键是**不能给出法律结论**：系统只指出"与哪条规则不符、差异在哪、建议什么条件、是否需要转人工"。定性是人的责任。

## What Changes

- 新增 `agents/regulatory` subgraph：`build_query → retrieve → answer → cite_check`
- 新增知识库：20 条手写语料（银行内部政策 / 国际惯例 / mock 筛查名单）
- 新增 `ingest.py`：语料 → 切块 → 向量化 → 内存索引，支持全量重建
- 实现**两种输入模式**：
  - `enriched` —— 有字段表，检索式结合字段生成
  - `raw` —— 用户直接扫原始文档，从正文推断检索要素
- 实现 `cite_check`：chunk_id 命中原检索 + 关键实体覆盖，失败**降级不删除**
- 实现覆盖声明与 `escalate_to_human` 的 6 条可复算判定
- 实现时效匹配：按交易日期取当时生效版本

**不在本 change 内**：真实法规库接入、定时同步、rerank、语义蕴含判断（NLI）、其他法域。

## Capabilities

### New Capabilities

- `regulatory-advice`：法规检索、两种输入模式、适用性匹配、覆盖声明、转人工

### Modified Capabilities

无。

## 与 Agent 4 的拆分

原 `agent-regulatory-verifier` 拆为 `agent-regulatory` 与 `agent-audit`。理由：

- 两份输出物的消费者不同：`legal` / `R-` findings 给前端与闸门；`verification` 给闸门与开发团队
- 验收标准不同：Agent 3 靠检索命中与引用支持率；Agent 4 靠检查器的拦截能力
- 同一个 change 里，"生成侧自查"与"独立第三方校验"容易在实现上被合并，而这个合并会破坏校验的独立性

## Impact

- 新增 `app/agents/regulatory/*`、`app/knowledge/ingest.py`、`knowledge/*.md`、`tests/test_regulatory.py`
- 依赖 `poc-skeleton` 的 `EditState.docs` / `fields` / `legal` / `retrieved` / `StageReport`
- 依赖 `poc-skeleton` 共享层的 `parse`（`raw` 模式）
- 依赖 embedding API
- 风险：语料内容必须由 A/B 提供，C 不自撰法规内容
- 风险：`raw` 模式无 `business_type` 时规则匹配会落空，必须靠 `business_type_uncertain` 显式暴露，否则前端会显示"未发现问题"

## 与其他 Agent 的接缝

| 方向 | 交付物 | 对下游的承诺 |
|---|---|---|
| Agent 1 → Agent 3 | `docs.full_text` / `fields` | `full_text` 与原文逐字一致，未改写未概括 |
| Agent 3 → Agent 4 | `legal` / `retrieved` / `R-` findings | `input_mode` 可信；每个 `chunk_id` 都在 `retrieved` 中 |
| Agent 3 → 前端 | `legal.coverage` / `escalate_to_human` | 未覆盖时必为 `true`，不会静默显示"无问题" |
