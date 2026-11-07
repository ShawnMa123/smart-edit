# Design: Agent 1 标准化

> Contract 真相源在 `changes/poc-skeleton/design.md`。本文件只描述 Agent 1 的实现策略与判定细节。
> `parse` / `extract` / `normalize` 属于共享层 `app/parsing/`，**Agent 1 不是它们的私有者**。

## 职责边界

**做**：把原始材料变成系统可识别的范式数据，每个值可跳回原文。

**不做**：

| 不做 | 归谁 |
|---|---|
| 补原文没有的内容 | 谁都不做 —— 这是硬约束 |
| 判断金额是否合理、材料是否齐全 | Agent 2 |
| 判断合规 | Agent 3 |
| 改写、润色、概括、摘要 | 谁都不做 |

> **"不修改、不拓展关键信息"的可执行形式**：对原文的每一次读取、转换、放行都必须写 `TrailEntry`。
> `summarize` / `rewrite` / `drop` 三种 op 出现即视为越界，Agent 4 报 `fail`。
> 这不是靠 prompt 里写"请不要改写"实现的，是靠日志可查。

## 输入

| 来源 | 形态 | 处理路径 |
|---|---|---|
| 客户邮件 | 纯文本正文 + 附件 | `parse` 提取正文，附件逐个解析 |
| 单据 PDF | 文本型 PDF | `parse` 提取段落 + 页码 + bbox |
| 合同 / 要约 | 长文本 PDF | 同上，注意上下文长度（见"长文档"） |
| 表格型申请表 | 表格型 PDF | **POC 不实现**，见下 |
| 粘贴文本 | 纯文本 | `parse` 直接分段 |

### 申请表 / 原始表单的处理策略

业务上这是主场景之一（客户提交银行提供的申请表单），但 POC 明确不做：

- 契约已预留 `Source.form_label` 字段，自由文本时恒为 `None`
- 表单路径需要的额外能力：栏目名识别、表格结构还原、栏目与 `fields.yaml` 的直接映射
- **POC 的表达方式**：表单型 PDF 走自由文本路径；若文本层可读则正常抽取，栏目名记入 `FieldValue.label`
- 演示时明确说明这是扩展位，不是遗漏

> 这样处理的原因是：不为了尚未确定的输入类型把 `parse` 写复杂，但契约上不留返工点。

## 节点

```text
parse → extract → normalize
```

| 节点 | 调模型 | 职责 | 归属 |
|---|---|---|---|
| `parse` | 否 | 文件 → `ParsedDoc`（blocks + full_text + errors） | 共享层 |
| `extract` | **是** | `ParsedDoc` → 候选字段 + 候选 span + label | 共享层 |
| `normalize` | 否 | 规范化 + `fields.yaml` 映射 + 三分类判定 | 共享层 |

**整个 Agent 1 只调一次模型**，在 `extract`。其余全是代码 —— 这样"同输入同输出"的范围尽可能大。

### `parse`

```python
def parse(files: list[SourceFile]) -> dict:
    docs, errors = [], []
    for f in files:
        try:
            doc = _parse_one(f)
            if not doc.full_text.strip():
                raise ScanLikeError("无文本层，疑为扫描件")
            docs.append(doc)
        except Exception as e:
            errors.append({"file_id": f.id, "reason": str(e)})
    return {"docs": docs, "parse_errors": errors}
```

失败处理：单文件失败记入 `errors` 继续；**全部失败** → `fields = {}` + `StageReport(status="failed")`，主图据此判 `fail`。

### `extract`

```python
def extract(docs, fields_yaml) -> dict:
    record(state, agent="agent1", stage="extract", op="llm_call",
           model=MODEL, prompt_hash=h, detail={"docs": len(docs)})
    candidates = llm.with_structured_output(CandidateList).invoke(prompt)
    for c in candidates:
        record(state, agent="agent1", stage="extract", op="emit",
               before=c.span, after=c.raw_value,
               ref=f"{c.file_id}/{c.page}")
    return {"candidates": candidates}
```

prompt 硬约束：**必须逐字复制原文片段作为 span，不得改写、不得拼接跨段落内容**。

长文档处理：单份 > 32k token 时按 `ParsedBlock` 分批抽取，每次带业务类型提示词做相关性过滤。
**过滤掉的页面必须记 `op="pass"` 并在 `detail` 写明"与 guarantee 业务无关，未抽取"** —— 不能静默跳过。

### `normalize`

```python
def classify(candidate, parsed_text_normalized) -> str:
    if candidate.raw_value is None:
        return "missing"
    if candidate.span and normalize_ws(candidate.span) in parsed_text_normalized:
        return "extracted"
    return "inferred"
```

`normalize_ws` 处理：空白折叠、全半角统一、连字符归一（`‐` `‑` `–` `—` → `-`）、引号统一。
**不处理这一步会导致大量本该 `extracted` 的字段掉成 `inferred`。**

## 值规范化规则

| 类型 | 规则 | 例 | `normalized_from` |
|---|---|---|---|
| 金额 | `Decimal`，2 位小数，去千分位 | `USD 500K` → `500000.00` | `USD 500K` |
| 币种 | ISO 4217 三位大写 | `usd` → `USD` | `usd` |
| 日期 | ISO 8601 | `2026-12-31` | 原样 |
| 日期（歧义） | 按字段 `date_order` 解释；未声明则 `notes=["date_ambiguous"]` 且降为 `inferred` | `12/03/26` | `12/03/26` |
| 国别 | ISO 3166-1 alpha-2 | — | 原样 |
| 名称 | **仅去首尾空白**，不改大小写与拼写 | ` ABC Trading ` → `ABC Trading` | 原样 |
| 地址 | 折叠空白，不改写 | — | 原样 |

### 关于名称大小写

`value` **保持原文大小写，不做 upper()**。原因：名称一致性比对由 Agent 2 负责，比对时双方各自归一化；
若 Agent 1 提前大写，`normalized_from` 之外的原始形态就丢了，而合规场景需要展示客户原文。
统一约定见 `poc-skeleton` 的接缝清单。

## `fields.yaml`

```yaml
- key: guarantee_amount
  label: 保函金额                 # 原文中该字段的常见称呼
  aliases: ["金额", "AMOUNT", "保函金额"]
  type: decimal
  stage:
    normalize: [precision, thousands]     # A 负责：怎么转成合规形式
    validate: [required, positive]        # B 负责：业务上允不允许
  max_length: 18
  charset: '0-9.'
  required: true
  date_order: null
```

**`stage` 标签是关键**：同一份字典被两个 Agent 读，但每条约束只有一个 owner。
A 只管"能不能转成合规形式"，B 只管"这个值业务上允不允许"。

## 输出

| 键 | 内容 |
|---|---|
| `docs` | `list[ParsedDoc]` |
| `fields` | `dict[str, FieldValue]`，`fields.yaml` 中定义的 |
| `extra_fields` | `dict[str, FieldValue]`，字典外的，不得混入 `fields` |
| `business_type` | `guarantee` / `unsupported` |
| `stages` | `StageReport` per stage |
| `trail` | `TrailEntry` 追加 |

### 业务类型判定

依据优先级：文档中的明确声明（"保函"/"GUARANTEE"/"URDG"）> 字段组合特征 > 无法判定。

- 判定为 `guarantee` → 正常
- 判定为其他类型或无法判定 → `unsupported`，且 MUST 记录依据（或缺失依据）
- **MUST NOT 为了保证下游能跑而强行选一个类型**

## 失败与降级

| 场景 | 表现 | 降级 |
|---|---|---|
| 单文件解析失败 | `ParsedDoc.errors` 非空 | 该文件不参与后续，其余继续 |
| 全部文件失败 | `docs = []` | `fields = {}`，`StageReport(status="failed")`，整次运行 `fail` |
| 扫描件（无文本层） | `parse` 抛 `ScanLikeError` | 记入 errors，明确提示"扫描件不支持"，**不得返回空字符串伪装成功** |
| `extract` 输出不合 schema | 重试一次 | 二次失败 → `StageReport(status="partial")` |
| 某字段值超长 | — | 截断 + `notes=["truncated"]` + Finding `N-xxx`（`kind="invalid_value"`, `severity="warn"`） |
| 日期歧义 | — | `notes=["date_ambiguous"]`，`status` 降为 `inferred` |

> 注意：Agent 1 会产出 Finding，`source="normalization"`，ID 前缀 `N-`。
> 这是 `Finding.source` 需要第三个值的原因。

## 独立触发

Agent 1 的三个阶段全部属于共享层，独立触发即"只跑 `parse`"或"只跑 `parse → extract`"。

| 触发范围 | 前置要求 | 产出 |
|---|---|---|
| 只 `parse` | 有 `files` | `docs` |
| `parse → extract` | 有 `files` | `docs` + `candidates`（**注意：`candidates` 不是 `fields`**） |
| 完整 Agent 1 | 有 `files` | `docs` + `fields` + `business_type` |

**只跑到 `extract` 时不写 `fields`** —— 未经 `normalize` 的值不满足契约（没有三分类判定、没有规范化），
下游若看见 `fields` 有值会误以为可用。

## 测试

```text
tests/test_parsing.py
  test_pdf_blocks_have_page_and_bbox
  test_scan_like_pdf_raises_not_silent
  test_partial_failure_continues
  test_same_pdf_two_paths_identical_blocks    # 独立触发与完整流程解析一致

tests/test_normalize.py
  test_amount_normalized_from_preserved
  test_currency_iso4217
  test_date_ambiguous_downgraded_to_inferred
  test_name_case_preserved
  test_span_not_found_becomes_inferred
  test_span_whitespace_normalized_match       # 归一化后能匹配上
  test_undefined_field_goes_to_extra_fields
  test_oversize_field_truncated_with_finding

tests/test_agent1_trail.py
  test_every_extracted_field_has_trail_entry
  test_skipping_pages_recorded_as_pass
```
