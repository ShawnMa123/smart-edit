# Proposal: Agent 2 要件校验

## Why

字段抽出来了不等于能走审批。真实业务里最常卡住一线员工的是"这个值填得不对"和"材料不全"，这些判断需要业务规则经验但不需要法律判断，可以按业务类型固化成本清单与规则。

Agent 2 的定位是**逐字段的值校验**：值是否合法、是否符合银行内部业务参数、必需的内容是否具备。它只报问题，不改值。

## What Changes

- 新增 `agents/verify` subgraph：`pick_checklist → check_fields → check_completeness → check_rules`
- 新增 `requirements.yaml` 要件清单（按业务类型）
- 值校验分两类：格式类（纯代码，`fields.yaml` 的 `stage=validate` 约束）与语义类（模型判定，识别"填的不是这一栏该填的东西"）
- 区分 `missing`（确实没交，阻断）与 `not_found`（交了没抽出，不阻断）
- 产出 `B-` 命名空间的 Finding，`blocking` 由 `requirements.yaml` 的规则声明决定
- 前置缺失时**拒绝执行**，不返回空 findings

**不在本 change 内**：法律合规判断与制裁筛查（Agent 3）、跨单据一致性比对（见下）。

## Capabilities

### New Capabilities

- `business-verification`：逐字段值校验、要件齐全性、业务参数规则
- `eval-benchmark`：离线评测的格式与口径（L1/L2/L3/L5 真值格式、指标定义、报告范围）

> `eval-benchmark` 放在本 change 而不是单独的 change，原因是 L1（字段真值）与 L2（规则真值）
> 的标注工作由 B 承担，且 gold 格式直接约束 Agent 1 的输出形态与 Agent 2 的规则表达。
> 它定义的是**离线**评测，与 Agent 4 的在线校验是两回事，MUST NOT 混用。

### Modified Capabilities

无。

## 影响面说明：跨单据一致性暂不实现

同一字段在多份单据中取值不同（发票金额 ≠ 合同金额）是典型的"信息不准确"场景，但本 change 不实现：

- `EditState.fields` 键唯一，一个字段只能存一个值，无法表达"发票金额 500,000；合同金额 480,000"
- 要支持需引入单据维度，是契约级改动，牵动 Agent 1 输出、`eval/gold` 格式、以及合同/发票样本
- POC 输入以自由文本 PDF 为主，单据结构尚未确定

**这是有意的时间盒决策，不是遗漏。** 演示时应主动说明该限制。

## Impact

- 新增 `app/agents/verify/*`、`requirements.yaml`、`tests/test_verify.py`、`tests/test_rules.py`
- 依赖 `poc-skeleton` 的 `EditState.fields` / `findings` / `business_type` / `StageReport`
- 依赖 `agent-normalize` 的 `fields.yaml` 中 `stage=validate` 的约束声明
- 本 change 同时承担 `eval/gold/` 与 `eval/gold_rules/` 的标注工作
- 闸门实现归 `poc-skeleton`；本 change 只声明闸门应读取的判定依据
- 风险：要件清单属业务知识，必须由熟悉审批要求的人确认，不能靠推断

## 与其他 Agent 的接缝

| 方向 | 交付物 | 对下游的承诺 |
|---|---|---|
| Agent 1 → Agent 2 | `fields` / `extra_fields` / `business_type` | `value` 保留原文大小写，`status` 三分类可信 |
| Agent 2 → Agent 4 | `findings`（`B-`）/ `stages` | `evidence` 非空泛；`blocking` 与 `requirements.yaml` 一致 |
| Agent 2 → 闸门 | `findings` | 新产出的 Finding `resolved=false` |
