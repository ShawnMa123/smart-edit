# Tasks: Agent 3 法规合规

> Owner: C
> 前置：`poc-skeleton` 契约冻结；共享层 `parse` 可用（`raw` 模式依赖）

## 1. 语料

- [ ] 1.1 定义语料条目 schema（`id` / `title` / `body` / `applies_to` / `jurisdictions` / `effective_from` / `source`）
- [ ] 1.2 收到 A 提供的 银行内部政策摘要，落到 `knowledge/bank_policy.md`
- [ ] 1.3 收到 B 提供的惯例要点（URDG 758 / ISP98 / UCP 600），落到 `knowledge/conventions.md`
- [ ] 1.4 编写 `knowledge/sanctions.mock.md`，显著标注"非真实名单，仅演示"
- [ ] 1.5 `app/knowledge/ingest.py`：切块（≤500 token，重叠 50）→ 向量化 → 写索引
- [ ] 1.6 `ingest.py` 支持全量重建，输出条数与耗时
- [ ] 1.7 `tests/test_ingest.py`：改语料 → 重建 → 检索结果同步变化

## 2. 检索

- [ ] 2.1 `retrieve`：`InMemoryVectorStore` 向量 top-5
- [ ] 2.2 `retrieve`：关键词兜底，与向量结果合并去重
- [ ] 2.3 `retrieve`：结果写入 `state.retrieved`
- [ ] 2.4 自测 20 个问题，记录 top-5 命中情况

## 3. 检索式生成（两模式）

- [ ] 3.1 `build_query`（`enriched`）：从字段表生成 3-5 个检索式
- [ ] 3.2 `build_query`（`raw`）：从正文提取主体/国别/金额/期限表述，生成 3-5 个检索式
- [ ] 3.3 `raw` 模式：从正文推断 `business_type`，推不出置 `coverage.business_type_uncertain`

## 4. 解答与自查

- [ ] 4.1 `answer`：输出 `claims[]`、`applicable_rules[]`、`coverage`
- [ ] 4.2 `answer`：每条 claim 含 `text` / `chunk_id` / `kind` / `support`
- [ ] 4.3 `answer`：无依据时输出 `support="insufficient"` + `chunk_id=null`，不得编造
- [ ] 4.4 `cite_check`：chunk_id 必须来自本次 `retrieved`，否则降级（不删除）
- [ ] 4.5 `cite_check`：关键实体（金额/日期/国别/规则号）覆盖校验
- [ ] 4.6 `cite_check`：全部降级动作写入 trail

## 5. 覆盖与转人工

- [ ] 5.1 `coverage`：写入 `jurisdictions` / `standards` / `unavailable` / `business_type_uncertain` / `notes`
- [ ] 5.2 空检索 → `unavailable=true`，summary 写"法规建议未覆盖"
- [ ] 5.3 `escalate_to_human`：实现 6 条触发条件
- [ ] 5.4 时效匹配：按 `transaction_date` 取当时生效版本
- [ ] 5.5 交易日期不可用 → 当前版本 + `coverage.notes` + 转人工
- [ ] 5.6 mock 名单命中 → `severity="critical"` + `blocking=false`

## 6. Finding

- [ ] 6.1 `R-` 前缀自增，`source="regulatory"`，`kind="regulatory_risk"`
- [ ] 6.2 `raw` 模式下 `field_keys=[]`
- [ ] 6.3 `evidence` 指向正文片段或 chunk 原文
- [ ] 6.4 重复触发时清除旧的 `source="regulatory"` findings 与旧 `legal`

## 7. 测试

- [ ] 7.1 `test_empty_retrieval_sets_unavailable`
- [ ] 7.2 `test_empty_retrieval_never_says_no_issue`
- [ ] 7.3 `test_fabricated_chunk_id_downgraded_not_deleted`
- [ ] 7.4 `test_entity_missing_in_cited_chunk`
- [ ] 7.5 `test_raw_mode_without_business_type_sets_uncertain`
- [ ] 7.6 `test_raw_mode_findings_have_empty_field_keys`
- [ ] 7.7 `test_escalate_rules`（6 条各一条）
- [ ] 7.8 `test_mock_hit_is_critical_but_not_blocking`
- [ ] 7.9 `test_transaction_date_missing_falls_back_with_note`
- [ ] 7.10 `test_same_doc_two_modes_identical_parse`

## 8. L3 评测（格式见 `agent-verify/specs/eval-benchmark/`）

- [ ] 8.1 `eval/gold_retrieval.json`：20 个问题 + 每题应命中的 `chunk_id`
- [ ] 8.2 计算 Recall@5 与 MRR，写入 `eval/report.md`
- [ ] 8.3 抽 50 条 claim 人工判 `supported` / `partial` / `unsupported` → `eval/citations_50.csv`
- [ ] 8.4 计算 `citation_support_rate` 与 `partial_support_rate`
- [ ] 8.5 构造 10 个超纲问题测拒答 → `refusal_rate`，目标 ≥ 0.9
- [ ] 8.6 报告中主动声明：未做 rerank、`citation_check` 只做实体覆盖未做语义蕴含

## 9. 接入与验收

- [ ] 9.1 替换 `poc-skeleton` 的占位 subgraph（`enriched` 路径）
- [ ] 9.2 `raw` 模式端到端跑通：只上传 PDF，直接得到 `legal(input_mode="raw")`
- [ ] 9.3 空检索时全链路无"无问题"措辞
- [ ] 9.4 虚构 chunk_id 能被 `cite_check` 降级
- [ ] 9.5 修改语料 → 重建索引 → 答案与引用同步变化（10 秒闭环）
