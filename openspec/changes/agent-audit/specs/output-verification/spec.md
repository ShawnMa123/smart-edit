# Output Verification

## Purpose

本 capability 定义 Agent 4 对其他 Agent 产出的证据链校验：通过统一注册表执行可判定检查
（schema、留痕、冲突、覆盖、引用、出处、锚点），产出可复算的可信度比率，并在失败项**可修复**时
触发一次受控重跑。它只回答"证据链是否成立"，不评业务对错；
`score` 仅用于展示，MUST NOT 参与阻断或重跑判定。范围不含业务判断、法规适用判断与主观评分。

## ADDED Requirements

### Requirement: 检查器注册表

系统 SHALL 通过统一注册表执行全部检查器，MUST NOT 因单个检查器异常而中断整体校验。

#### Scenario: 检查器统一签名
- **WHEN** 新增一个检查器
- **THEN** 其签名 MUST 为 `check(state: EditState) -> list[Issue]`，MUST NOT 写入 `EditState`

#### Scenario: 单个检查器抛异常
- **WHEN** 某检查器执行时抛出异常
- **THEN** 系统 MUST 记录一条 `level="fail"` 的 Issue 并继续执行其余检查器
- **AND** MUST NOT 整图失败，MUST NOT 静默跳过该检查器

#### Scenario: 全部检查器崩溃
- **WHEN** 所有检查器均抛出异常
- **THEN** `verification.verdict` MUST 为 `fail`

### Requirement: 契约符合性校验

系统 SHALL 校验三个 Agent 的输出符合状态契约。

#### Scenario: 缺必填键
- **WHEN** 任一 Agent 的输出缺少契约规定的必填键
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 空列表不得为 null
- **WHEN** `Finding.field_keys` 为 `null`
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: ID 命名空间
- **WHEN** `Finding.id` 的前缀与 `Finding.source` 不匹配
- **THEN** 产生 `level="fail"` 的 Issue

### Requirement: 操作日志校验

系统 SHALL 校验操作日志的完整性并检出越界操作。

#### Scenario: 越界操作
- **WHEN** `trail` 中存在 `op` 为 `summarize`、`rewrite` 或 `drop` 的条目
- **THEN** 产生 `level="fail"` 的 Issue，并指出对应条目 ID

#### Scenario: 抽取缺日志
- **WHEN** 存在 `status="extracted"` 的字段但 `trail` 中无对应 `emit` 条目
- **THEN** 产生 `level="warn"` 的 Issue

#### Scenario: 模型调用不可复现
- **WHEN** 某条 `llm_call` 条目缺 `prompt_hash`
- **THEN** 产生 `level="warn"` 的 Issue

#### Scenario: 范围性跳过必须说明理由
- **WHEN** `trail` 中存在 `op="pass"` 的条目但 `detail` 未说明理由
- **THEN** 产生 `level="warn"` 的 Issue

### Requirement: 结论冲突校验

系统 SHALL 检查不同 Agent 的结论之间是否存在事实前提上的矛盾。

#### Scenario: raw 模式跳过
- **WHEN** `legal.input_mode` 为 `raw`（Agent 2 未执行）
- **THEN** 系统 MUST 跳过本项校验，并记录 `StageReport(status="skipped")`
- **AND** MUST NOT 报告为"无矛盾"

#### Scenario: 事实前提矛盾
- **WHEN** Agent 2 判定某字段非法，而 Agent 3 的 claim 以该字段值为前提
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 不比合规标签
- **WHEN** 执行本项校验
- **THEN** 系统 MUST 比较事实前提与规则适用，MUST NOT 比较"合规/不合规"标签

### Requirement: 覆盖声明校验

系统 SHALL 校验 Agent 3 声称的覆盖范围是否有检索证据。

#### Scenario: 声称未覆盖但未声明
- **WHEN** `coverage.unavailable` 为 `true` 但 summary 未声明未覆盖
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 声称覆盖但无证据
- **WHEN** `coverage.unavailable` 为 `false` 但 `retrieved` 为空
- **THEN** 产生 `level="fail"` 的 Issue

### Requirement: 引用支持校验

系统 SHALL 校验每条 claim 的引用是否成立。

#### Scenario: 引用不在检索结果中
- **WHEN** claim 的 `chunk_id` 不在本次 `retrieved` 中
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 关键实体未被引用支持
- **WHEN** claim 含金额、日期、国别或规则号，而被引 chunk 原文中没有该实体
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 依据不足却带引用
- **WHEN** claim 的 `support="insufficient"` 但 `chunk_id` 非空
- **THEN** 产生 `level="warn"` 的 Issue

### Requirement: 出处校验

系统 SHALL 校验标记为 `extracted` 的字段出处真实成立。

#### Scenario: 标了出处却没有
- **WHEN** `status="extracted"` 但 `source` 为 `null`
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 出处片段不在原文中
- **WHEN** `source.span` 归一化后无法在对应文件的全文里找到
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 片段粒度过大
- **WHEN** `span` 长度超过配置上限
- **THEN** 产生 `level="warn"` 的 Issue，提示可能是整行而非最小片段

### Requirement: 锚点校验

系统 SHALL 校验每条 Finding 是否指向真实存在的字段或位置。

#### Scenario: 字段不存在
- **WHEN** `field_keys` 中的键既不在 `fields` 也不在 `extra_fields`
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 证据为空
- **WHEN** `evidence` 为空字符串或仅含空白
- **THEN** 产生 `level="fail"` 的 Issue

#### Scenario: 引用与来源不匹配
- **WHEN** `source="regulatory"` 但 `citation` 为 `null`，或 `source="business"` 但 `citation` 非空
- **THEN** 产生 `level="warn"` 的 Issue

### Requirement: 判定结果

系统 SHALL 依据 Issue 的最高等级给出结论。

#### Scenario: 存在 fail
- **WHEN** 任一 Issue 的 `level` 为 `fail`
- **THEN** `verification.verdict` MUST 为 `fail`，且 MUST 抑制发布

#### Scenario: 仅有 warn
- **WHEN** 无 `fail` 级 Issue 但存在 `warn`
- **THEN** `verdict` MUST 为 `warn`

#### Scenario: 阶段未完成时不得通过
- **WHEN** `stages` 中存在 `status` 不为 `done` 的必需阶段
- **THEN** `verdict` MUST NOT 为 `pass`

### Requirement: 可信度必须可复算

系统 SHALL 以可复算的比率表达可信度，MUST NOT 使用不可复算的综合分。

#### Scenario: 三个比率
- **WHEN** 完成校验
- **THEN** `credibility` MUST 包含 `provenance_coverage`、`citation_support`、`inferred_unconfirmed_rate`
- **AND** 每一项 MUST 能由 `EditState` 独立复算，任意两名成员算出的值 MUST 一致

#### Scenario: 分母为零
- **WHEN** 某比率的分子分母均为 0
- **THEN** 该项 MUST 返回 `1.0` 或 `null`，MUST NOT 返回 `0.0`

#### Scenario: 不做加权合成
- **WHEN** 输出可信度
- **THEN** 系统 MUST NOT 将三个比率合成为单一数值替代它们

#### Scenario: 分数不参与判定
- **WHEN** `verification.score` 存在
- **THEN** 它 MUST NOT 影响 `verdict`，MUST NOT 触发重跑，且 MUST 与三个比率同时展示

### Requirement: 受控重跑

系统 SHALL 在可判定检查失败时允许有限次重跑。

#### Scenario: 只有 fail 触发
- **WHEN** 存在 `level="fail"` 的 Issue 且预算未耗尽
- **THEN** 系统 MAY 触发重跑
- **AND** `warn` / `info` / `score` MUST NOT 触发重跑

#### Scenario: 反馈携带失败项
- **WHEN** 触发重跑
- **THEN** 反馈 MUST 包含失败项定位与期望，MUST NOT 只传分数

#### Scenario: 输入类失败不重跑
- **WHEN** 失败原因为文件不可解析或原文确实缺数据
- **THEN** 系统 MUST NOT 重跑，MUST 直接降级为人工复核

#### Scenario: 预算
- **WHEN** `repair_count` 达到 1 或总重跑次数达到 3
- **THEN** 系统 MUST 停止重跑并标注"已重跑 N 次仍未通过"

#### Scenario: 按归属选择性重跑
- **WHEN** 失败项可归因到特定 Agent
- **THEN** 系统 MUST 只重跑该 Agent 及其下游，MUST NOT 重跑全部阶段

### Requirement: 不越界

系统 MUST NOT 产出业务判断或法律结论。

#### Scenario: 不做业务判断
- **WHEN** 检查发现字段抽取有误
- **THEN** 系统 MUST 只报证据链问题，MUST NOT 判断业务上该值应该是什么

#### Scenario: 不评价法规适用
- **WHEN** 检查 Agent 3 的输出
- **THEN** 系统 MUST 只校验引用是否成立、覆盖是否属实，MUST NOT 判断法规适用是否恰当

#### Scenario: 不可单独触发
- **WHEN** 调用方请求只运行 Agent 4
- **THEN** 系统 MUST 拒绝并说明其校验对象是其他 Agent 的输出
