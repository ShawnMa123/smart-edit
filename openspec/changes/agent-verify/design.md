# Design: Agent 2 要件校验

> Contract 真相源在 `changes/poc-skeleton/design.md`。
> 职责范围：**逐字段的值校验 + 齐全性 + 业务参数**。跨单据一致性见"范围说明"。

## 职责边界

| 做 | 不做 |
|---|---|
| 逐字段校验：非法值、非法字符、超长、格式不符 | 改变字段值（只报，不改） |
| 必填字段与必备单据的齐全性 | 判断条款是否合法（Agent 3） |
| 业务参数：金额精度、日期先后、期限上限、币种有效性 | 决定是否放行（闸门职责） |
| 区分 `missing`（没交）与 `not_found`（交了没抽出） | 补数据、改数据 |

## 输入

| 键 | 必需 | 缺失时 |
|---|---|---|
| `fields` | **是** | 拒绝执行，返回缺失项 |
| `business_type` | **是** | `unsupported` → 跳过校验并置 `StageReport(status="skipped")` |
| `extra_fields` | 否 | 不参与校验，但记入 `StageReport` |
| `docs` | 否 | 单据齐全性检查降级为"仅依据字段判定"，并在 `detail` 说明 |

> **前置缺失时 MUST 拒绝执行，不得返回 `findings = []`。**
> 空 findings 与"没跑"在数据结构上必须可区分，否则前端会显示"无问题"而实际什么都没查。

## 节点

```text
pick_checklist → check_fields → check_completeness → check_rules
```

| 节点 | 调模型 | 职责 |
|---|---|---|
| `pick_checklist` | 否 | 按 `business_type` 取 `requirements.yaml` 片段 |
| `check_fields` | 是 | 逐字段判定：非法字符、格式不符、语义异常（如"申请人名称不是机构名"） |
| `check_completeness` | 是 | 必备字段 + 必备单据是否具备，区分 `missing` / `not_found` |
| `check_rules` | 否 | 纯代码：金额精度、日期先后、期限上限、币种有效性 |

三个检查节点各自写 `StageReport`，`agent` 恒为 `agent2`。

### `check_fields`：为什么需要模型

纯代码能查的：长度、字符集、正则、必填。这些在 `check_rules` 里做。

必须模型的："这个值填的是不是这一栏该填的东西"。例：

```text
applicant_name = "USD 500000"          → 语义异常（值是金额不是名称）
beneficiary_name = "详见附件"           → 占位文本，等于没填
goods_description = "N/A"               → 同上
```

这类问题正则写不完，且是 一线员工实际最常遇到的"信息不准确"。
**但它的输出只能是 Finding，不能改值。**

### `check_completeness`：双判法

```text
1. 关键词/结构预判：requirements.yaml 的 detect 列表命中 → present（不求模型）
2. 未命中 → 模型判定：这批材料里有没有该单据
3. 两者冲突 → 以模型为准，confidence 降低，Finding 加 needs_review 标记
```

### `check_rules`：纯代码

| 规则 | 判据 | severity |
|---|---|---|
| 金额精度 | 小数位 > 2 或为负 | critical |
| 金额范围 | 超过 `requirements.yaml` 上限 | warn |
| 日期先后 | 到期日 ≤ 生效日 | critical（blocking） |
| 日期范围 | 生效日早于今天超过 1 年 | warn |
| 期限上限 | 超过 `max_tenor_months` | warn |
| 币种 | 不在 ISO 4217 有效列表 | critical |
| 必填 | `status == "missing"` | 见下 |

## `requirements.yaml`

```yaml
guarantee:
  required_fields:
    - key: applicant_name
      blocking: true
    - key: beneficiary_name
      blocking: true
    - key: guarantee_amount
      blocking: true
    - key: expiry_date
      blocking: true

  required_documents:
    - id: REQ-DOC-001
      name: 商业发票
      blocking: true
      detect: ["商业发票", "COMMERCIAL INVOICE", "INVOICE"]
    - id: REQ-DOC-002
      name: 保函申请书
      blocking: true
      detect: ["保函申请", "APPLICATION FOR GUARANTEE", "GUARANTEE APPLICATION"]

  limits:
    max_tenor_months: <INT>        # 占位：由业务方确认，不可自行推断
    max_amount: <DECIMAL>          # 占位
    min_amount: <DECIMAL>          # 占位
```

> ⚠️ **`requirements.yaml` 中的具体阈值不在本仓库给出。** 这些是业务参数，必须由熟悉审批要求的人确认
> （见 tasks 1.4）。spec 只规定"存在这一类限制以及超限时的 severity"，不规定数值。
> 直接照抄任何示例数字都会导致规则失效或误报。

### `missing` 的阻断规则

| Finding kind | 触发 | severity | blocking |
|---|---|---|---|
| `missing`（确实没交） | 字段 `status="missing"` 且 `required.blocking` | critical | **true** |
| `not_found`（交了没抽出） | 单据存在但字段没抽出来 | warn | **false** |
| `invalid_value` | 规则判定不合法 | 见规则表 | critical → true |

**`not_found` 不阻断** —— 这是操作问题不是客户问题，阻断会让柜员去追客户补一份已经交过的材料。

## `stage` 归属的落实

`fields.yaml` 中每条约束带 `stage` 标签（见 `agent-normalize`）：

```yaml
- key: applicant_name
  max_length: 70
  stage:
    normalize: [thousands]        # A 负责
    validate: [charset, required] # B 负责 ← 本 Agent 读这些
```

Agent 2 MUST 只执行 `stage=validate` 的约束。同一条约束不得被两个 Agent 各实现一遍。

## Finding 生成

```python
Finding(
    id=f"B-{seq:03d}",
    source="business",
    kind=...,                  # missing | not_found | invalid_value
                               #        | inconsistent | policy_violation
    rule_id=...,
    severity=...,              # critical | warn | info
    blocking=...,              # 见上表，不得由 severity 单独推导
    resolved=False,
    resolution=None,
    field_keys=[...],          # 无关联字段时为空列表 []
    message=...,
    evidence=...,              # 必须是原文片段或字段值，不得为空泛描述
    citation=None,
    suggestion=...,
)
```

`evidence` 的硬要求举例：

```text
✗ "金额格式不正确"
✓ "guarantee_amount = '500000.123'，小数位 3 位，超出 2 位限制"
```

## 范围说明：跨单据一致性

同一字段在多份单据中取值不同（发票金额 ≠ 合同金额）是典型的"信息不准确"场景。

**本 change 不实现跨单据一致性比对**，原因：

- `EditState.fields` 是 `dict[str, FieldValue]`，键唯一，一个字段只能存一个值
- 要表达"发票金额 500,000；合同金额 480,000"需要引入单据维度，属于契约级改动
- 当前输入以自由文本 PDF 为主、申请表未纳入 POC，单据结构尚未确定

**在契约引入单据维度之前，本 Agent 只做单值校验。**
若后续要做，需要：`EditState` 增加按单据分组的字段视图、`FieldValue.doc_type` 参与定位、
`eval/gold` 增加多单据样本。这三项都是独立的工作量，不在 POC 时间盒内。

## 失败与降级

| 场景 | 表现 | 降级 |
|---|---|---|
| `fields` 为空 | 拒绝执行 | 返回缺失项清单，`StageReport(status="skipped")` |
| `business_type = unsupported` | 跳过全部检查 | 一条 `warn` 说明未校验，**零 blocking** |
| `check_fields` 模型超时 | — | `StageReport(status="partial")`，仅保留代码规则结果 |
| `requirements.yaml` 缺该业务类型 | — | 视为"规则缺失"，`StageReport(status="failed")` |
| 单个检查节点抛异常 | — | 记录后继续其他节点，不得整图失败 |

## 独立触发

| 触发范围 | 前置 | 产出 |
|---|---|---|
| `agent2` 完整 | `fields` 非空 + `business_type` 非空 | `findings`（`B-` 前缀）+ `stages` |
| `agent2` 但 `fields` 为空 | — | **拒绝**，不返回空 findings |

独立触发时的 findings 累加：入口先清掉 `source == "business"` 的旧 findings，再写入。
主图路径由 `reset` 负责，不重复处理。

## 测试

```text
tests/test_verify.py
  test_missing_vs_not_found_produce_different_kind
  test_not_found_is_not_blocking
  test_missing_required_field_is_blocking
  test_unsupported_business_type_zero_blocking
  test_empty_fields_rejected_not_empty_findings
  test_field_value_not_modified_by_checker
  test_evidence_is_not_vague

tests/test_rules.py
  test_date_order
  test_amount_precision
  test_tenor_limit
  test_currency_iso4217
  test_amount_negative

tests/test_verify_standalone.py
  test_reject_when_fields_missing
  test_rescope_clears_previous_business_findings
```
