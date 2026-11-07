# Proposal: Agent 1 标准化

## Why

一线员工最大的工作量是把客户材料里的信息逐字段敲进内部系统。这一步只需要"看得准、格式对"，不需要判断业务，因此可以交给系统，并且必须做到每个值都能跳回原文 —— 否则员工不敢用。

同时，"不修改、不拓展关键信息"不能只是一句 prompt 要求。本 change 把它变成**可事后查证的事实**：对原文的每次操作都留痕，越界改写可被 Agent 4 检出。

## What Changes

- 定义 Agent 1 的职责边界与失败降级：解析、抽取、规范化、三分类判定
- 明确输入形态：客户邮件、文本型 PDF、合同片段、粘贴文本；**申请表 / 表单型 PDF 列为扩展位**（契约预留 `Source.form_label`，POC 不实现）
- 明确"只改形式不改事实"的可判定口径：名称不改大小写、`span` 为最小片段、模糊表述不得确定化、不得概括
- 明确 `fields.yaml` 的**职责分离**：`stage=normalize` 归本 Agent，`stage=validate` 归 Agent 2
- 定义 `business_type` 的判定依据与"无依据时不得臆断"
- 定义三个阶段的独立触发能力（只跑 `parse` / `parse+extract` / 完整）

**不在本 change 内**：OCR、扫描件、表单结构还原、多业务类型字段集切换。
`parse` / `extract` / `normalize` 的实现属于 `poc-skeleton` 的共享层，本 change 只声明其行为要求。

## Capabilities

### New Capabilities

- `normalization`：原始材料到结构化字段的转换、值规范化、出处绑定、留痕

### Modified Capabilities

无。

## Impact

- `app/parsing/*` 的行为由本 change 的 spec 约束，但代码归属 `poc-skeleton`
- 新增 `fields.yaml`（含 `stage` 归属标签）、`tests/test_parse.py`、`tests/test_normalize.py`、`tests/test_agent1_trail.py`
- 依赖 `poc-skeleton` 的 `FieldValue` / `Source` / `TrailEntry` / `StageReport` 契约
- **Agent 1 会产出 Finding**（`source="normalization"`，ID 前缀 `N-`），因此 `Finding.source` 需要第三个枚举值 —— 与 `poc-skeleton` 的契约一并确认
- 依赖模型 API 支持结构化输出（Q4）
- 风险：输入若含扫描件，`parse` 工作量翻倍，需先确认 Q2

## 与其他 Agent 的接缝

| 方向 | 交付物 | 对下游的承诺 |
|---|---|---|
| Agent 1 → Agent 2 | `fields` / `extra_fields` / `business_type` | `value` 保留原文大小写；`status` 三分类可信；`source.span` 是最小片段 |
| Agent 1 → Agent 3 | `docs`（`full_text`）/ `fields` | `full_text` 与原文逐字一致，未改写未概括 |
| Agent 1 → Agent 4 | `trail` | 每次模型调用与转换都有记录，含 `prompt_hash` |
