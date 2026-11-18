# Tasks: Agent 3 法规合规

> Owner: C
> 前置：`poc-skeleton` 契约冻结；共享层 `parse` 可用（`raw` 模式依赖）

## 1. 语料

- [x] 1.1 定义语料条目 schema（`id` / `title` / `body` / `applies_to` / `jurisdictions` / `effective_from` / `source`）
- [ ] 1.2 收到 A 提供的 银行内部政策摘要，落到 `knowledge/bank_policy.md`
- [ ] 1.3 收到 B 提供的惯例要点（URDG 758 / ISP98 / UCP 600），落到 `knowledge/conventions.md`
- [ ] 1.4 编写 `knowledge/sanctions.mock.md`，显著标注"非真实名单，仅演示"
- [x] 1.5 `app/knowledge/ingest.py`：切块（≤500 token，重叠 50）→ 向量化 → 写索引
- [x] 1.6 `ingest.py` 支持全量重建，输出条数与耗时
- [x] 1.7 `tests/test_ingest.py`：改语料 → 重建 → 检索结果同步变化

## 2. 检索

- [x] 2.1 `retrieve`：`InMemoryVectorStore` 向量 top-5
- [x] 2.2 `retrieve`：关键词兜底，与向量结果合并去重
- [x] 2.3 `retrieve`：结果写入 `state.retrieved`
- [x] 2.4 自测 20 个问题，记录 top-5 命中情况

## 3. 检索式生成（两模式）

- [x] 3.1 `build_query`（`enriched`）：从字段表生成 3-5 个检索式
- [x] 3.2 `build_query`（`raw`）：从正文提取主体/国别/金额/期限表述，生成 3-5 个检索式
- [x] 3.3 `raw` 模式：从正文推断 `business_type`，推不出置 `coverage.business_type_uncertain`

## 4. 解答与自查

- [x] 4.1 `answer`：输出 `claims[]`、`applicable_rules[]`、`coverage`
- [x] 4.2 `answer`：每条 claim 含 `text` / `chunk_id` / `kind` / `support`
- [x] 4.3 `answer`：无依据时输出 `support="insufficient"` + `chunk_id=null`，不得编造
- [x] 4.4 `cite_check`：chunk_id 必须来自本次 `retrieved`，否则降级（不删除）
- [x] 4.5 `cite_check`：关键实体（金额/日期/国别/规则号）覆盖校验
- [x] 4.6 `cite_check`：全部降级动作写入 trail

## 5. 覆盖与转人工

- [x] 5.1 `coverage`：写入 `jurisdictions` / `standards` / `unavailable` / `business_type_uncertain` / `notes`
- [x] 5.2 空检索 → `unavailable=true`，summary 写"法规建议未覆盖"
- [x] 5.3 `escalate_to_human`：实现 6 条触发条件
- [x] 5.4 时效匹配：按 `transaction_date` 取当时生效版本
- [x] 5.5 交易日期不可用 → 当前版本 + `coverage.notes` + 转人工
- [x] 5.6 mock 名单命中 → `severity="critical"` + `blocking=false`

## 6. Finding

- [x] 6.1 `R-` 前缀自增，`source="regulatory"`，`kind="regulatory_risk"`
- [x] 6.2 `raw` 模式下 `field_keys=[]`
- [x] 6.3 `evidence` 指向正文片段或 chunk 原文
- [x] 6.4 重复触发时清除旧的 `source="regulatory"` findings 与旧 `legal`

## 7. 测试

- [x] 7.1 `test_empty_retrieval_sets_unavailable`
- [x] 7.2 `test_empty_retrieval_never_says_no_issue`
- [x] 7.3 `test_fabricated_chunk_id_downgraded_not_deleted`
- [x] 7.4 `test_entity_missing_in_cited_chunk`
- [x] 7.5 `test_raw_mode_without_business_type_sets_uncertain`
- [x] 7.6 `test_raw_mode_findings_have_empty_field_keys`
- [x] 7.7 `test_escalate_rules`（6 条各一条）
- [x] 7.8 `test_mock_hit_is_critical_but_not_blocking`
- [x] 7.9 `test_transaction_date_missing_falls_back_with_note`
- [x] 7.10 `test_same_doc_two_modes_identical_parse`

## 8. L3 评测（格式见 `agent-verify/specs/eval-benchmark/`）

- [ ] 8.1 `eval/gold_retrieval.json`：20 个问题 + 每题应命中的 `chunk_id`
- [x] 8.2 计算 Recall@5 与 MRR，写入 `eval/report.md`
- [ ] 8.3 抽 50 条 claim 人工判 `supported` / `partial` / `unsupported` → `eval/citations_50.csv`
- [ ] 8.4 计算 `citation_support_rate` 与 `partial_support_rate`
- [ ] 8.5 构造 10 个超纲问题测拒答 → `refusal_rate`，目标 ≥ 0.9

  > **保持未勾（owner 2026-11-19 决定，已知缺口）**
  > spec.md:155 的判据是 `legal.coverage.unavailable=true`；实测 agent3 真实输出 **0/10**。
  > 根因：`answer.py:122` 定义为 `unavailable = not retrieved`，而远程 BM25 对超纲文本仍返回
  > 5 条无关 chunk。**不是设计变更**：spec 判据（11-07）与 `escalate_to_human` 6 条件（11-07）
  > 同日写入、实现（11-09）一次落地；变的是外部检索服务从本地 20 条手写语料换成远程 143 部。
  > 注意 `escalate_to_human` 10/10 不能当作"识别超纲"：raw 模式下 `not filters.as_of` 恒成立，
  > 域内文档同样为 true（见 `eval/refusal_agent3.md`）。
  > **实测输出形态**：既不是拒绝回答、也不是编造——`stage=done`、`unavailable=false`、
  > summary 写「检索到 5 条相关条文」、5 条 claim 全 `supported`（问个税却返回独立保函条文）。
  > 零编造法规、零法律定性，但把无关条文当相关结果照常输出，且无「主题不在语料范围」声明。
  > **修复方向（此前建议已作废）**：原建议「所有 claim 均 insufficient 时置 unavailable=true」
  > 经实测永不触发——超纲与域内 claims 全 `supported`，超纲 top1 分数也是 1.0，低分阈值分不开。
  > 剩余路径：① Shawn 服务端加相关性重排/阈值；② 本仓库新 change 引入语义蕴含判断
  > （`proposal.md:21` 明确排除）；③ 改 `build_query` 主题约束（BM25 兜底未必有效）。
  > **边界**：不能改评测脚本把 `escalate=true` 算成拒答（改考卷迁就答案，且域内也 true）；
  > 不能改 spec 冻结判据；产品代码可改但属新 change。详见 `eval/refusal_agent3.md`。 
- [x] 8.6 报告中主动声明：未做 rerank、`citation_check` 只做实体覆盖未做语义蕴含

## 9. 接入与验收

- [x] 9.1 替换 `poc-skeleton` 的占位 subgraph（`enriched` 路径）
- [x] 9.2 `raw` 模式端到端跑通：只上传 PDF，直接得到 `legal(input_mode="raw")`
- [x] 9.3 空检索时全链路无"无问题"措辞
- [x] 9.4 虚构 chunk_id 能被 `cite_check` 降级
- [x] 9.5 修改语料 → 重建索引 → 答案与引用同步变化（10 秒闭环）
