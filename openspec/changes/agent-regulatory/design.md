# Design: Agent 3 法规合规

> Contract 真相源在 `changes/poc-skeleton/design.md`。
> 本文件描述 Agent 3 的检索链路、两种输入模式与输出口径。

## 职责边界

| 做 | 不做 |
|---|---|
| 检索 银行内部政策 + 外部法规/惯例，找不符要求之处 | 出"可做/不可做"的最终结论 |
| 每条结论绑定可追溯的引用 | 替代正式制裁筛查系统 |
| 显式声明覆盖范围 | 未覆盖却声称覆盖 |
| 判定是否需要转人工 | 修改字段或补数据 |

## 核心原则：指出，但不定性

```text
✓ "该条款未约定展期通知方式，URDG 758 第 26 条要求书面通知"
✓ "国别为 XX，命中内部政策 P-007，建议取得合规部门前置确认"
✗ "该保函不合规"
✗ "该交易可以做"
```

输出永远是「适用规则 + 具体条款 + 差异点 + 建议条件 + 是否转人工」。
这条决定了 Agent 4 的 `conflict_check` 怎么判"矛盾"—— 比的是**规则适用与风险结论**，不是"合规/不合规"的标签。

## 两种输入模式

用户可以直接拿原始文档跑合规扫描，不必等 Agent 1。这带来两种模式：

| input_mode | 触发 | 输入 | 丢失的信息 |
|---|---|---|---|
| `enriched` | 完整流程，或先跑了 `parse→extract→normalize` | `docs` + `fields` + `business_type` | — |
| `raw` | 用户直接发起全文扫描 | 只有 `docs`（`full_text`） | `business_type`、`fields` |

### `raw` 模式的三个硬要求

```text
1. business_type 缺失 → 从正文推断；
   推断不出 MUST 置 coverage.business_type_uncertain = true，
   且 MUST NOT 输出"未发现问题"

2. 无字段表 → build_query 改为从正文提取检索要素（国别/金额/条款类型/货物描述），
   并在 coverage.notes 声明"基于正文检索，未使用字段表"

3. 无字段锚点 → findings 的 field_keys MUST 为空列表，
   evidence MUST 指向正文片段
```

第 1 条最关键：`applies_to` 匹配靠 `business_type`，没有它就匹配不到规则，
返回空 findings —— **前端会显示"未发现问题"，而实际是一条规则都没匹配上**。

### 为什么不做两条独立代码路径

```text
完整流程：  parse → extract → normalize → agent3.enriched
独立扫描：  parse →                       agent3.raw
```

差别只在中间两步在不在，解析用的是同一个共享实现。
若各写一份，同一份 PDF 会切出不同段落、`evidence` 定位到不同位置，
演示时"同一文档两次扫描结论不同"且无法解释。

## 知识库

```
knowledge/
  bank_policy.md          # 银行内部政策摘要（A 提供）
  conventions.md          # 国际惯例要点：URDG 758 / ISP98 / UCP 600（B 提供）
  sanctions.mock.md       # mock 名单，显著标注"非真实名单，仅演示"
```

**内容由 A/B 提供，C 只负责结构与管道。** 理由：法规内容写错比代码写错危险得多；
演示时被问"这条 URDG 758 条款出自哪里"必须答得上来。

### 语料条目结构

```yaml
- id: K-001
  title: 保函期限的审批上限
  body: 保函期限超过 <N> 个月时需升级至上一级审批……
  applies_to: [guarantee]
  jurisdictions: [<CC>, <CC>]          # 占位：按实际法域填写
  effective_from: 2025-01-01
  source: 银行内部作业规程（占位）
```

### 切块与索引

- 按二级标题切块，单块 ≤ 500 token，块间重叠 50 token
- `InMemoryVectorStore.from_documents(chunks, embedding)`
- 关键词兜底：chunk 文本子串匹配命中的加分，与向量结果合并去重
- `python ingest.py` 全量重建（20 条语料，< 5 秒）

不做：rerank、查询改写模型、增量索引、外部向量库。

## 节点

```text
build_query → retrieve → answer → cite_check
```

| 节点 | 调模型 | 职责 |
|---|---|---|
| `build_query` | `enriched`: 是 / `raw`: 是 | 生成 3-5 个检索式 |
| `retrieve` | 否 | 向量 top-5 + 关键词兜底，写 `retrieved` |
| `answer` | 是 | 产出 `claims[]` + `applicable_rules[]` + `coverage` |
| `cite_check` | 否 | 见下 |

### `build_query`

```python
# enriched：从字段表生成
[业务类型, 国别, 金额档位, 货物描述, 条款类型]  → 3-5 个检索式

# raw：从正文生成
[推定业务类型, 正文中出现的主体/国别/金额/期限表述] → 3-5 个检索式
```

### `answer`

要求模型对每条 claim 给出 `chunk_id`。**找不到依据时必须返回 `chunk_id=None` + `support="insufficient"`，
不得编造 chunk_id。** 判据来自 prompt 与结构约束，验证在 `cite_check`。

### `cite_check`（Agent 3 内部，代码）

```python
# 1. chunk_id 必须来自本次 retrieved
valid = {c["chunk_id"] for c in state["retrieved"]}
for claim in claims:
    if claim["chunk_id"] not in valid:
        claim["chunk_id"] = None
        claim["support"] = "insufficient"   # 降级，不删除

# 2. 关键实体必须出现在被引原文
entities = extract_entities(claim["text"])   # 金额/日期/国别/规则号，正则
missing = [e for e in entities if e not in chunk_by_id[claim["chunk_id"]]["text"]]
if missing:
    claim["support"] = "insufficient"

# 3. 语义蕴含 —— POC 不做
```

**降级不删除**：claim 保留但标为依据不足，核对台仍展示，员工知道"系统查到过这一点但没证据"。

> 与 Agent 4 的 `citation_check` 的分工：`cite_check` 是生成侧的自我降级（在 Agent 3 subgraph 内），
> `citation_check` 是独立的第三方校验（Agent 4，跨全部 Agent 的产出）。
> 两者判据相同但**不能合并** —— 否则等于让生成者自己宣布合格。

## 输出

| 键 | 内容 |
|---|---|
| `legal.input_mode` | `enriched` / `raw` |
| `legal.applicable_rules` | `list[ApplicableRule]`，含 `rule_id` / `version` / `effective_from` / `chunk_id` |
| `legal.claims` | `list[Claim]`，每条带 `chunk_id` 或 `support="insufficient"` |
| `legal.coverage` | `{jurisdictions, standards, unavailable, business_type_uncertain, notes}` |
| `legal.escalate_to_human` | 见下 |
| `retrieved` | 供 Agent 4 的 `citation_check` / `coverage_check` 使用 |
| `findings` | `R-` 前缀，`source="regulatory"`，`kind="regulatory_risk"` |

### `escalate_to_human` 判定

命中任一即置 `true`：

```text
1. coverage.unavailable = true          （检索为空）
2. coverage.business_type_uncertain     （raw 模式推不出业务类型）
3. 交易涉及未支持的法域或标准
4. 存在 support="insufficient" 的 claim 且其为 risk 类
5. 命中 mock 名单
```

### 检索为空的处理

```text
retrieved 为空
  → coverage.unavailable = true
  → escalate_to_human = true
  → summary 明确写"法规建议未覆盖"
  → MUST NOT 写"未发现问题" / "无适用规则"
```

### mock 名单命中

**不阻断、不判定**，只提示并要求人工复核：

```python
Finding(
    source="regulatory",
    kind="regulatory_risk",
    severity="critical",      # 严重级别高
    blocking=False,           # 但不阻断 —— 正式筛查由专门系统负责
    message="交易对手/国别命中演示名单（非真实名单），需人工复核",
)
```

> 早期文档写作"`critical` 的 `info` 级提示"，`severity` 与 `title` 矛盾。
> 这里定为 `severity="critical"` + `blocking=False`：**严重但不由本系统拦**。

### 时效匹配

`applicable_rules` 按交易日期匹配当时生效版本：

```python
rule.effective_from <= transaction_date   # 取满足条件的最新版本
```

`transaction_date` 来源：`fields` 中的日期类字段（`issue_date` / `effective_date`）。
`raw` 模式下若无可用日期 → `coverage.notes` 声明"未能确定交易日期，按当前有效版本适用"，
并置 `escalate_to_human = true`。

## 失败与降级

| 场景 | 表现 | 降级 |
|---|---|---|
| 检索为空 | `retrieved = []` | `coverage.unavailable=true`，禁止输出"无问题" |
| embedding API 失败 | — | `StageReport(status="failed")`，`escalate_to_human=true` |
| `answer` 输出虚构 chunk_id | — | `cite_check` 降级为 `insufficient`，不删除 |
| 交易日期不可用 | — | 按当前版本适用 + 写入 `coverage.notes` + 转人工 |
| `raw` 模式推不出业务类型 | — | `business_type_uncertain=true`，禁止输出"未发现问题" |
| 法规库为空 | `ingest.py` 未跑 | `StageReport(status="failed")`，`unavailable=true` |

## 独立触发

| 触发范围 | 前置 | 产出 |
|---|---|---|
| `enriched` | `docs` + `fields` + `business_type` | 完整 `legal` + `retrieved` + `R-` findings |
| `raw` | 只需 `files`（自动补 `parse`） | `legal(input_mode="raw")` + `retrieved` + `R-` findings |

**Agent 3 是唯一支持直接从原始文件启动的 Agent** —— Agent 2 需要 `extract`，Agent 4 需要他人输出。

## 测试

```text
tests/test_regulatory.py
  test_empty_retrieval_sets_unavailable
  test_empty_retrieval_never_says_no_issue
  test_fabricated_chunk_id_downgraded_not_deleted
  test_entity_missing_in_cited_chunk
  test_raw_mode_without_business_type_sets_uncertain
  test_raw_mode_findings_have_empty_field_keys
  test_escalate_rules                     # 5 条触发条件各一条
  test_mock_hit_is_critical_but_not_blocking
  test_transaction_date_missing_falls_back_with_note

tests/test_ingest.py
  test_rebuild_index_reflects_corpus_change
  test_chunk_size_and_overlap
```
