# Spec Delta

## Purpose

定义配置驱动的确定性字段提取：系统按版本化的 extraction profile 从当前解析文档中定位字段值，保留出处与置信度，并在无法唯一确定时显式降级，而不是回放固定 fixture 或静默猜测。

## ADDED Requirements

### Requirement: Extraction profiles are versioned configuration

系统 SHALL 从版本化的 extraction profile（JSON）读取字段提取规则；profile MUST 只引用 `fields.yaml` 已声明的字段 key，并 MUST 使用受控的 `value_kind`（`amount` / `date` / `currency` / `integer` / `text` / `clause_text`）表达值形状，MUST NOT 接受任意正则、脚本或外部命令。

#### Scenario: Valid profile loads with a stable identity
- **WHEN** 加载一个字段 key 均存在、`value_kind` 受支持的 profile
- **THEN** 系统 MUST 返回 profile id、version 与内容 hash
- **AND** 该 identity MUST 可写入 audit 报告

#### Scenario: Unknown field or value kind is rejected
- **WHEN** profile 引用了 `fields.yaml` 未定义的 key，或声明了不受支持的 `value_kind`
- **THEN** 加载 MUST 失败并给出可读原因
- **AND** MUST NOT 退化为空 profile 或忽略该字段继续运行

#### Scenario: Inline pattern is not accepted
- **WHEN** profile 试图内联一个自定义正则或脚本
- **THEN** 系统 MUST 拒绝该配置
- **AND** 新格式 MUST 通过增加受测的 `value_kind` 支持，而不是放开配置注入

### Requirement: Deterministic extraction reads the current document

系统 SHALL 在存在 extraction profile 时，从本次 `parse` 产出的 `docs.blocks` 中提取字段，MUST NOT 使用固定 fixture 的候选值。提取 MUST 以 label/alias 定位为起点，并 MUST 为每个命中记录 `file_id`、`page`、`bbox`、`span` 与 `form_label`。

#### Scenario: Label and value in one block
- **WHEN** 当前文档包含 `Issue Date: 12/03/26`，且 profile 声明 `issue_date` 的 alias `ISSUE DATE`
- **THEN** 系统 MUST 产出 `issue_date` 候选 `12/03/26`
- **AND** `_source.span` MUST 只包含值本身，MUST NOT 包含 label
- **AND** 该候选 MUST 可在原文中定位

#### Scenario: Value on the next block
- **WHEN** profile 允许 `same_or_next_block`，且 label 与值分处相邻两个 block
- **THEN** 系统 MUST 产出候选，并 MUST 在来源中记录实际所在 block 的页码与 span
- **AND** MUST NOT 跨页拼接；跨页时 MUST 降级处理

#### Scenario: Amount and currency use approved parsers
- **WHEN** profile 声明 `guarantee_amount` 为 `value_kind=amount`、`currency` 为 `value_kind=currency`
- **THEN** 系统 MUST 复用现有金额/币种规范化逻辑
- **AND** 产出的 `raw_value` MUST 来自原文，规范化后的值 MUST 供 `normalize` 判定类型

#### Scenario: Missing label produces no candidate
- **WHEN** 当前文档没有某个字段的 label/alias
- **THEN** 系统 MUST NOT 为该字段编造候选
- **AND** 必填字段 MUST 由 `normalize` 生成 `missing` 占位，而不是从 `fields` 中缺席

### Requirement: Ambiguous extraction MUST NOT be silently resolved

系统 SHALL 在多个候选值不同且无法按确定性规则唯一选择时，保留冲突并降级为未确认状态，MUST NOT 静默选择其中一个。

#### Scenario: Two different values for one field
- **WHEN** 同一字段在两个 block 中命中不同值，且置信度接近
- **THEN** 该字段 MUST 标记为 `unconfirmed`（或等价的需要人工确认状态）
- **AND** 系统 MUST 在 trail 中记录两个候选及未选原因
- **AND** 依赖该字段的规则 MUST NOT 得到 `pass`

#### Scenario: Duplicate values are de-duplicated deterministically
- **WHEN** 同一字段多次命中相同值
- **THEN** 系统 MUST 只保留一个候选
- **AND** 选择顺序 MUST 可复现（同 block + 精确 label 优先，其次 alias，再其次 next block）

### Requirement: Extraction provenance is reported and reproducible

系统 SHALL 在同一输入文本与同一 profile 下产生相同的字段与来源，并在 audit 报告中记录提取来源、profile identity 与模型调用次数。

#### Scenario: Same text produces the same extraction
- **WHEN** 同一文档文本与同一 profile 被提取两次
- **THEN** 两次的字段 key、值、状态、span 与 profile hash MUST 相同
- **AND** stage report MUST 记录 `model_calls=0`

#### Scenario: Report names the extraction source
- **WHEN** 审计使用确定性 profile
- **THEN** `verification` MUST 暴露 `source=deterministic`、profile id/version/hash
- **AND** MUST 暴露找到与缺失的字段数量

#### Scenario: Fixture remains an explicit compatibility path
- **WHEN** 请求没有指定 extraction profile
- **THEN** 系统 MUST 保留现有 fixture/LLM 提取路径
- **AND** 报告 MUST 明确标注来源为 `fixture` 或 `llm`，MUST NOT 伪装成 deterministic

### Requirement: Model fallback is opt-in and never overrides deterministic hits

系统 SHALL 只在 profile 明确允许且确定性提取未找到或置信度不足时调用模型补提取；模型候选 MUST 标记为未确认，MUST NOT 覆盖已有的确定性候选。

#### Scenario: Deterministic hit is final
- **WHEN** 某字段已由确定性提取得到值
- **THEN** 模型补提取 MUST NOT 替换该值
- **AND** MUST NOT 因模型给出不同值而改变确定性来源

#### Scenario: Fallback disabled
- **WHEN** profile 的 `llm_fallback.enabled` 为 false
- **THEN** 系统 MUST 不发起模型调用
- **AND** 未找到的字段 MUST 保持缺失/需人工补充

#### Scenario: Fallback candidate is unconfirmed
- **WHEN** 模型为缺失字段返回候选
- **THEN** 该候选 MUST 标记为低置信度/未确认
- **AND** 依赖该字段的规则 MUST 要求人工确认后才能 `pass`