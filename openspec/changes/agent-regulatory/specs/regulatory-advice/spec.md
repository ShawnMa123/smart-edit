# Regulatory Advice

## ADDED Requirements

### Requirement: 检索必须可追溯

系统 SHALL 在知识库中检索与当前交易相关的政策与规则，并保留检索结果供下游校验。

#### Scenario: 检索命中
- **WHEN** 检索返回结果
- **THEN** 结果 MUST 写入 `EditState.retrieved`，每项含 `chunk_id`、`source_doc`、`text`、`score`

#### Scenario: 检索无结果
- **WHEN** 检索返回空
- **THEN** `legal.coverage.unavailable` MUST 为 `true`，`legal.escalate_to_human` MUST 为 `true`
- **AND** 系统 MUST 输出"法规建议未覆盖"
- **AND** MUST NOT 输出"未发现问题"、"无适用规则"或任何等价表述

#### Scenario: 知识库为空
- **WHEN** 索引未建立或语料为空
- **THEN** `StageReport.status` MUST 为 `failed`，且 MUST NOT 视为检索完成

### Requirement: 两种输入模式

系统 SHALL 支持带字段表与不带字段表两种输入，并显式声明所用模式。

#### Scenario: 完整流程
- **WHEN** 已执行 `parse → extract → normalize`
- **THEN** `legal.input_mode` MUST 为 `enriched`，检索式 MUST 结合字段表生成

#### Scenario: 直接扫描原始文档
- **WHEN** 用户直接对原始文件发起扫描，未执行抽取与规范化
- **THEN** 系统 MUST 自动补跑 `parse`，`legal.input_mode` MUST 为 `raw`
- **AND** MUST NOT 要求用户先完成 Agent 1

#### Scenario: raw 模式无字段锚点
- **WHEN** `input_mode` 为 `raw`
- **THEN** 产出的 Finding `field_keys` MUST 为空列表
- **AND** `evidence` MUST 指向正文片段

#### Scenario: raw 模式无业务类型
- **WHEN** `input_mode` 为 `raw` 且无法从正文推断业务类型
- **THEN** `legal.coverage.business_type_uncertain` MUST 为 `true`
- **AND** `legal.escalate_to_human` MUST 为 `true`
- **AND** MUST NOT 输出"未发现问题"

#### Scenario: 两种模式共用同一解析
- **WHEN** 同一文件分别以 `enriched` 与 `raw` 模式处理
- **THEN** 两次的 `ParsedDoc.blocks` MUST 逐块一致

### Requirement: 每条结论必须绑定引用

系统 SHALL 为每条法规类 claim 标注其依据的知识库条目。

#### Scenario: 有依据的结论
- **WHEN** 模型给出关于适用规则的判断
- **THEN** 该 claim MUST 携带 `chunk_id`，且该 `chunk_id` MUST 来自本次 `retrieved`
- **AND** `support` MUST 为 `supported`

#### Scenario: 无依据的结论
- **WHEN** 模型给出的判断找不到支撑条目
- **THEN** 该 claim MUST 标记 `support="insufficient"` 且 `chunk_id` MUST 为 `null`
- **AND** MUST NOT 携带虚构 `chunk_id`

#### Scenario: 校验失败降级不删除
- **WHEN** `cite_check` 判定某 claim 的引用不成立
- **THEN** 该 claim MUST 保留但降级为 `support="insufficient"`
- **AND** MUST NOT 从输出中删除

#### Scenario: 实体覆盖校验
- **WHEN** claim 中含有金额、日期、国别或规则号
- **THEN** 这些实体 MUST 出现在被引 chunk 的原文中，否则该 claim MUST 降级

### Requirement: 覆盖声明

系统 SHALL 显式声明本次分析的覆盖范围。

#### Scenario: 覆盖范围内
- **WHEN** 交易事实落在支持的法域与标准范围内
- **THEN** `legal.coverage` MUST 列出实际使用的法域、标准与版本

#### Scenario: 超出覆盖范围
- **WHEN** 交易涉及未支持的法域或标准
- **THEN** `legal.coverage.notes` MUST 说明缺口，`legal.escalate_to_human` MUST 为 `true`

#### Scenario: 覆盖范围不可推断
- **WHEN** 无法确定本次检索覆盖了哪些法域
- **THEN** `legal.coverage.notes` MUST 显式说明无法确定
- **AND** MUST NOT 留空表示"全覆盖"

### Requirement: 时效匹配

系统 SHALL 按交易日期匹配当时生效的规则版本。

#### Scenario: 规则版本已更新
- **WHEN** 交易日期早于当前规则的生效日
- **THEN** 系统 MUST 使用当时生效的版本，并在 `applicable_rules` 中标明版本与生效日期

#### Scenario: 交易日期不可用
- **WHEN** 无法从字段或正文确定交易日期
- **THEN** 系统 MUST 按当前有效版本适用，并在 `coverage.notes` 显式声明
- **AND** `legal.escalate_to_human` MUST 为 `true`

### Requirement: 指出问题但不定性

系统 SHALL 指出与政策或法规不符之处，MUST NOT 出具决定性法律结论。

#### Scenario: 输出形态
- **WHEN** 发现某项内容与规则不符
- **THEN** 输出 MUST 包含适用规则、具体条款、差异点与建议条件
- **AND** MUST NOT 包含"合规/不合规"、"可做/不可做"的判定

#### Scenario: 疑似命中筛查名单
- **WHEN** 交易对手或国别命中知识库中的 mock 名单
- **THEN** 系统 MUST 产出 `severity="critical"` 但 `blocking=false` 的 Finding，要求人工复核
- **AND** MUST NOT 出具放行或禁止的结论

#### Scenario: 不替代正式筛查
- **WHEN** 完成本 Agent 的检查
- **THEN** 系统 MUST 声明其结果不替代正式的制裁与出口管制筛查

### Requirement: 转人工判定

系统 SHALL 明确判断是否需要转人工，判定依据可复算。

#### Scenario: 触发转人工
- **WHEN** 命中以下任一条件：检索为空、业务类型不确定、涉及未支持法域、存在依据不足的风险类 claim、命中 mock 名单、交易日期不可用
- **THEN** `legal.escalate_to_human` MUST 为 `true`

#### Scenario: 未触发
- **WHEN** 以上条件均未命中
- **THEN** `legal.escalate_to_human` MUST 为 `false`

### Requirement: 阶段可独立触发

系统 SHALL 允许单独触发本 Agent，并支持从原始文件直接启动。

#### Scenario: 从原始文件启动
- **WHEN** 调用方只提供原始文件并请求运行 Agent 3
- **THEN** 系统 MUST 自动补跑 `parse` 并进入 `raw` 模式

#### Scenario: 写阶段状态
- **WHEN** 本 Agent 执行完毕
- **THEN** MUST 写入 `StageReport`，`agent` 为 `agent3`，并区分 `done` / `partial` / `failed`

#### Scenario: 重复触发不累加
- **WHEN** 在同一运行上第二次触发 Agent 3
- **THEN** 入口 MUST 先清除本 Agent 此前产出的 `source="regulatory"` 的 Finding 与旧 `legal`
