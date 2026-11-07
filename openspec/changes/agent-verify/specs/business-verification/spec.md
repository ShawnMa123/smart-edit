# Business Verification

## ADDED Requirements

### Requirement: 前置条件必须校验

系统 SHALL 在执行前校验所需的输入，MUST NOT 在前置缺失时静默返回空结果。

#### Scenario: 字段为空
- **WHEN** `fields` 为空或缺失
- **THEN** 系统 MUST 拒绝执行并返回缺失项清单
- **AND** MUST NOT 返回 `findings = []` 作为结果
- **AND** `StageReport.status` MUST NOT 为 `done`

#### Scenario: 业务类型为空
- **WHEN** `business_type` 为空或缺失
- **THEN** 系统 MUST 拒绝执行并说明缺失

### Requirement: 按业务类型选择要件清单

系统 SHALL 依据 `business_type` 从 `requirements.yaml` 选取对应的要件清单。

#### Scenario: 支持的业务类型
- **WHEN** `business_type` 为 `guarantee`
- **THEN** 系统 MUST 加载该类型的必备字段、必备单据与业务限制

#### Scenario: 不支持的业务类型
- **WHEN** `business_type` 为 `unsupported`
- **THEN** 系统 MUST 跳过全部检查，产出一条 `warn` 说明未校验
- **AND** MUST NOT 产出任何 `blocking`，`StageReport.status` MUST 为 `skipped`

#### Scenario: 规则缺失不得假装通过
- **WHEN** `requirements.yaml` 中不存在该业务类型的条目
- **THEN** `StageReport.status` MUST 为 `failed` 且 `reason` 非空

### Requirement: 逐字段值校验

系统 SHALL 校验每个字段的值是否合法、是否为该栏目应有的内容。

#### Scenario: 格式类非法值
- **WHEN** 字段值违反 `fields.yaml` 中 `stage=validate` 声明的字符集或长度约束
- **THEN** 系统 MUST 产生 `kind="invalid_value"` 的 Finding，`field_keys` MUST 包含该字段

#### Scenario: 语义类非法值
- **WHEN** 字段值在语义上不属于该栏目的内容（如申请人为纯数字、名称栏填"详见附件"或"N/A"）
- **THEN** 系统 MUST 产生 `kind="invalid_value"` 的 Finding

#### Scenario: 校验不修改值
- **WHEN** 校验发现某字段值不合法
- **THEN** 系统 MUST NOT 修改 `EditState.fields` 中的任何值，只产出 Finding

#### Scenario: 证据不可空泛
- **WHEN** 产出一条值校验类 Finding
- **THEN** `evidence` MUST 包含具体字段值与违反的约束，MUST NOT 使用"格式不正确"一类无信息描述

#### Scenario: 只执行本 Agent 负责的约束
- **WHEN** 读取 `fields.yaml` 中的约束
- **THEN** 系统 MUST 只执行标注为 `stage=validate` 的约束，MUST NOT 重复实现 `stage=normalize` 的转换逻辑

### Requirement: 区分缺失与未识别

系统 MUST 区分"材料确实没交"与"交了但没抽出来"。

#### Scenario: 单据确实缺失
- **WHEN** 材料中不存在某份必备单据，且模型确认无相关文档
- **THEN** 产生 `kind="missing"` 的 Finding，`suggestion` MUST 提示向客户补交

#### Scenario: 单据存在但未识别
- **WHEN** 材料中存在该单据但未能抽取出相关字段
- **THEN** 产生 `kind="not_found"` 的 Finding，`suggestion` MUST 提示重新解析
- **AND** MUST NOT 提示客户补交

#### Scenario: 未识别不阻断
- **WHEN** Finding 的 `kind` 为 `not_found`
- **THEN** `blocking` MUST 为 `false`

#### Scenario: 齐全性双判冲突
- **WHEN** 关键词预判与模型判定结论不一致
- **THEN** 系统 MUST 以模型判定为准、降低 `confidence`，并在 `evidence` 中说明判定依据

### Requirement: 业务参数规则

系统 SHALL 以确定性代码校验业务参数。

#### Scenario: 日期顺序
- **WHEN** 到期日早于或等于生效日
- **THEN** 产生 `critical` 且 `blocking: true` 的 Finding

#### Scenario: 金额精度
- **WHEN** 金额小数位超过 2 位或为负数
- **THEN** 产生 `critical` 的 Finding

#### Scenario: 期限上限
- **WHEN** 保函期限超过 `requirements.yaml` 声明的上限
- **THEN** 产生 `warn` 的 Finding，`suggestion` MUST 提示需升级审批

#### Scenario: 币种无效
- **WHEN** 币种不在 ISO 4217 有效列表
- **THEN** 产生 `critical` 的 Finding

#### Scenario: 参数规则不调用模型
- **WHEN** 执行金额精度、日期、期限、币种校验
- **THEN** 系统 MUST 以确定性代码实现，MUST NOT 调用模型

### Requirement: 阻断判定

系统 SHALL 依据规则声明而非严重级别单独决定是否阻断。

#### Scenario: 阻断由规则声明
- **WHEN** 一条 Finding 的 `severity` 为 `critical`
- **THEN** 其 `blocking` MUST 由该规则在 `requirements.yaml` 中的声明决定，MUST NOT 仅由 `severity` 推导

#### Scenario: 必填字段缺失
- **WHEN** 必填字段的 `status` 为 `missing` 且该字段声明为阻断
- **THEN** 产生 `blocking: true` 的 Finding

#### Scenario: 新产出的 Finding 未处理
- **WHEN** 系统产出一条 Finding
- **THEN** `resolved` MUST 为 `false`，`resolution` MUST 为 `null`

### Requirement: Finding 必须可定位

系统 SHALL 为每条 Finding 记录其关联的字段。

#### Scenario: 字段级 Finding
- **WHEN** 一条 Finding 由某个字段触发
- **THEN** `field_keys` MUST 包含该字段，且该字段存在于 `EditState.fields` 或 `extra_fields`

#### Scenario: 无关联字段的 Finding
- **WHEN** Finding 由单据缺失触发
- **THEN** `evidence` MUST 说明缺少的是哪份单据，`field_keys` MUST 为空列表（非 `null`）

#### Scenario: ID 命名空间
- **WHEN** 本 Agent 产生 Finding
- **THEN** `id` MUST 使用 `B-` 前缀且在本 Agent 内自增，MUST NOT 与 `N-` / `R-` 冲突

### Requirement: 不越界到法律判断

系统 MUST NOT 产出法律或合规结论。

#### Scenario: 疑似合规问题
- **WHEN** 检查中发现可能需要法规判断的情形（如条款缺失、国别敏感）
- **THEN** 系统 MUST 只产出 `info` 或 `warn` 提示，MUST NOT 给出"合规/不合规"结论

#### Scenario: 不替代他人职责
- **WHEN** 遇到属于 Agent 1（值与原文不符）或 Agent 3（法规适用）的问题
- **THEN** 系统 MUST NOT 自行判定，MUST 交由对应 Agent 或留空

### Requirement: 阶段可独立触发

系统 SHALL 允许单独触发本 Agent。

#### Scenario: 独立触发的入口
- **WHEN** 调用方请求只运行 Agent 2
- **THEN** 系统 MUST 自动补跑其声明的前置阶段并校验前置条件

#### Scenario: 重复触发不累加
- **WHEN** 在同一运行上第二次触发 Agent 2
- **THEN** 入口 MUST 先清除本 Agent 此前产出的 `source="business"` 的 Finding，再写入新结果

#### Scenario: 写阶段状态
- **WHEN** 本 Agent 的任一检查节点执行完毕
- **THEN** MUST 写入对应的 `StageReport`，`agent` 为 `agent2`
