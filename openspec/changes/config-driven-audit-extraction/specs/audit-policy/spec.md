# Spec Delta

## Purpose

定义公司策略包与审计基准时间：审计以显式 `as_of` 日期和版本化 policy packs 评估当前文档字段，使“日期不得早于今天”“必须包含某条款”等公司规范可确定性执行、可重放，并在策略缺失或冲突时显式失败而不是给出干净结论。

## ADDED Requirements

### Requirement: Audit MUST use an explicit as-of date

系统 SHALL 为每次 audit 固定一个 `as_of` 日期，并 MUST 将该日期写入报告；规则引擎 MUST 从该上下文读取日期，MUST NOT 在纯函数内部直接读取系统时钟。

#### Scenario: Report records the audit date
- **WHEN** 一次 audit 完成
- **THEN** 报告 MUST 包含本次使用的 `as_of`
- **AND** 报告 MUST 包含 policy bundle 与 template 的版本标识

#### Scenario: Replay with the same as-of
- **WHEN** 同一文本、同一 `as_of` 与同一策略版本被审计两次
- **THEN** 两次的 findings、gate 与 coverage MUST 相同

#### Scenario: Different as-of changes only time-dependent rules
- **WHEN** 同一文本在两个不同 `as_of` 下审计
- **THEN** 只有依赖 `as_of` 的规则 MAY 改变结果
- **AND** 非时间规则 MUST 保持一致

### Requirement: Relative-date operands are restricted and typed

系统 SHALL 支持受控的 `relative_date` 操作数，且第一版 MUST 只允许 `today`；该操作数在比较前 MUST 被解析为与字段日期同类型的值。

#### Scenario: Issue date in the past
- **WHEN** `as_of` 为 2026-11-19，文档的 `issue_date` 为 2026-11-18，且公司规则要求 `issue_date <= today`
- **THEN** 该规则 MUST 产生 `finding`
- **AND** finding MUST 引用实际字段值与 `as_of`

#### Scenario: Issue date today
- **WHEN** `issue_date` 等于 `as_of`
- **THEN** 同一规则 MUST 产生 `pass`

#### Scenario: Unsupported relative value is rejected
- **WHEN** 规则声明 `relative_date` 为 `today` 之外的值（如任意表达式）
- **THEN** bundle 加载 MUST 失败
- **AND** MUST NOT 在运行时静默退化为某个日期

### Requirement: Company policy packs are publishable and versioned

系统 SHALL 以与现有 rule bundle 相同的方式加载公司 policy pack：只有 `published` 的包可参与审计，包 MUST 记录 id、version、owner、有效窗口与内容 hash。

#### Scenario: Published company pack runs
- **WHEN** 一个已发布的公司包声明 `guarantee_amount > 0` 或必含 `URDG 758`
- **THEN** 对应 check unit MUST 出现在计划中并被执行
- **AND** 报告 MUST 列出该包及其版本

#### Scenario: Unpublished or missing mandatory pack
- **WHEN** 公司包未发布、缺失或无法解析
- **THEN** 受影响的 checks MUST 为 `unable_to_assess` 或 run MUST 失败
- **AND** MUST NOT 读成“没有适用规则，因此通过”

#### Scenario: Pack cannot drop a mandatory rule
- **WHEN** 请求试图排除公司包或其中的强制规则
- **THEN** 该排除 MUST 被忽略
- **AND** verdict MUST 仍按包含该规则的策略计算

### Requirement: Policy conflicts MUST remain visible

系统 SHALL 在多个来源对同一字段/类别给出不同 gate 类型时报告冲突；冲突未解决时，受影响单元 MUST 为 `unable_to_assess`，受保护操作 MUST NOT 为 `allowed`。

#### Scenario: Customer template softens a hard rule
- **WHEN** 公司包对 `currency` 声明 `hard_block`，客户模板对同字段声明 `advisory`
- **THEN** 报告 MUST 列出冲突并命名两个来源
- **AND** 受影响单元 MUST 为 `unable_to_assess`
- **AND** gate MUST NOT 返回 `allowed`

#### Scenario: Two rules in one pack are not a conflict
- **WHEN** 同一个包同时包含某字段的 hard 与 advisory 规则
- **THEN** MUST NOT 报告为跨来源冲突
- **AND** 两条规则 MUST 各自执行

### Requirement: Template and explicit profile selection are bounded

系统 SHALL 允许 template 声明默认 extraction profile，并允许请求显式指定 profile；显式选择 MUST 只在该 profile 已发布且 `document_types` 匹配时生效，MUST NOT 放宽策略或选择未发布配置。

#### Scenario: Template selects the profile
- **WHEN** template 声明 `extraction_profile=guarantee-default`
- **THEN** 该次 audit 的提取 MUST 使用该 profile
- **AND** 报告 MUST 记录 profile 来自 template

#### Scenario: Explicit profile override
- **WHEN** 请求通过 `?profile=` 指定另一个已发布且类型匹配的 profile
- **THEN** 系统 MUST 使用该 profile
- **AND** MUST NOT 因此跳过 template 的 fields/clauses 或公司 policy packs

#### Scenario: Unknown or mismatched profile is refused
- **WHEN** 请求指定不存在、未发布或 document type 不匹配的 profile
- **THEN** 请求 MUST 被拒绝或 audit MUST 失败并说明原因
- **AND** MUST NOT 静默回退到 fixture

### Requirement: Audit results expose policy and extraction provenance together

系统 SHALL 在同一个 verification 中记录提取来源与策略来源，使同一份报告可以解释“值从哪来、按哪套规范判断、基准日是哪天”。

#### Scenario: Complete provenance block
- **WHEN** audit 使用 deterministic profile 与公司 policy pack
- **THEN** `verification` MUST 包含 extraction（source/profile/version/hash）、policy（bundles/template/as_of）
- **AND** 任一字段的 finding MUST 能关联到对应 profile 或 rule id

#### Scenario: Config failure is not an empty pass
- **WHEN** profile 或 policy 加载失败
- **THEN** audit MUST 返回 `failed` 或对应单元 `unable_to_assess`
- **AND** MUST NOT 返回 `findings=[]` 表示成功