# Proposal

## Why

当前 audit 的字段来自 `SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json` 的固定回放：无论 editor 里写的是哪份文档，`extract` 都返回同一组 `guarantee_number / guarantee_amount / issue_date`，后续 `normalize` 与 `audit` 审查的并不是当前文档。已有的 `GR-AMOUNT-POSITIVE`、`GR-EXPIRY-AFTER-ISSUE`、template field/clause expectations 因此无法作用于用户真正编辑的内容。

本 change 先把 **“从当前 editor 文本确定性提取字段 + 按公司规则确定性审查”** 做通，不引入 LLM：同一份文本必须得到同一份字段与 findings，且 `model_calls=0`。豆包语义复核留到后续 change。

## What Changes

- 新增 **extraction profile JSON**：按 `fields.yaml` 的字段 key 声明 label/alias、`value_kind`（amount/date/currency/integer/text/clause）、同块或下一块搜索、最大长度与置信度；不允许配置任意正则或脚本。
- 新增 **确定性提取器**：从 `parse` 产出的 `docs.blocks` 按 label/alias 定位当前文档值，复用现有金额/日期/币种规范化，生成带 `_source`（file/page/bbox/span）的候选；冲突或无法唯一确定时标为 `unconfirmed`，不静默挑选。
- `extract` 节点在有 profile 时走确定性路径，**不因没有 LLM 而失败**；无 profile 时保留现有 fixture/LLM 路径用于 demo 与回归。可选的 LLM 补提取默认关闭，本 change 不实现真实模型调用。
- 新增 **公司规则包**（rule bundle），复用现有 closed DSL 表达：Issue Date 不得早于审计基准日、Amount > 0（复用已有规则）、必须包含 URDG 758 / 付款条款、允许币种与金额上限等。
- DSL 增加受控的 **`relative_date: today`** 操作数；引擎从 `as_of` 读取日期，保持纯函数。`audit` 报告记录 `as_of`、profile id/version/hash、bundle 版本，保证可重放。
- Template 可声明 `extraction_profile`，现有 template 选择即同时决定提取 profile 与 policy packs；API 保留 `?profile=` 显式覆盖。
- Audit 结果暴露提取来源与字段覆盖：`deterministic | fixture | llm`、found/missing 数量、每个字段的 span 与状态；前端在 Assistant/Audit 面板显示来源、profile 版本与 `as_of`。
- 明确不做：真实豆包调用、语义条款判定、审批 gate 规则变更、数据库迁移、新的独立配置编辑 UI。

## Capabilities

### New Capabilities

- `audit-extraction`: 配置驱动的确定性字段提取：profile 校验、label/alias 定位、受控值类型、provenance/冲突处理、profile 版本与来源写入报告，以及 fixture 路径的兼容。
- `audit-policy`: 公司策略包与审计基准时间：`as_of` 驱动的 `relative_date` 规则、公司 rule bundle、与现有 template/policy 的合并、报告中的版本与基准日记录。

### Modified Capabilities

<!-- 无：现有 document-editor / document-import / rich-text-editing 的需求不变。 -->

## Impact

- **后端**：`app/configs/extraction/*.json`（新增）、`app/parsing/deterministic_extract.py`（新增）、`app/nodes/extract.py`、`app/rules/dsl.py`、`app/rules/engine.py`、`app/rules/bundles/*.yaml`（新增公司包）、`app/templates/*.yaml`（增加 profile 引用）、`app/audit/runner.py` / `app/nodes/audit.py` / `app/audit/report.py`（记录 `as_of` 与来源）、`app/api/main.py`（audit 阶段可选 `profile`）。
- **前端**：`web/src/components/AssistantPanel.tsx`（审计来源、profile 版本、`as_of`、字段覆盖展示）；不新增页面。
- **API**：复用 `POST /runs` 的 editor 文本；`POST /runs/{id}/stages/audit` 增加可选 `?profile=`；`verification` 增加 extraction/policy 元数据。无破坏性变更。
- **数据**：无数据库迁移；无审批/身份表变更。
- **测试**：profile loader、确定性提取、provenance/冲突、`as_of` 规则、公司 bundle、同文本可重放、fixture 兼容、UI 来源展示。
- **兼容性**：无 profile 时保持现有行为；`AUTH_MODE=fake` / `?demo=1` 的 fixture 演示路径继续可用，报告明确标注来源。