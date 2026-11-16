# Spec Delta

## Purpose

定义知识助手接入真实模型提供方（豆包/Ark，OpenAI 兼容接口）时的边界：配置启用、结构化输出校验、无工具与无网络、提供方与版本可追溯、超时与失败语义；让“更强模型”不削弱既有的无证据不结论与可复核要求。

## ADDED Requirements

### Requirement: 模型提供方由配置启用且禁止静默回退

系统 SHALL 通过显式配置选择模型提供方；未配置或配置无效时 MUST 以失败或 fixture 模式运行，MUST NOT 静默使用其他提供方或伪造模型输出。

#### Scenario: 配置真实提供方

- **WHEN** 部署配置指定了模型提供方、模型名与凭据
- **THEN** 运行 MUST 使用该提供方
- **AND** 运行记录 MUST 标明提供方与模型版本

#### Scenario: 未配置或凭据缺失

- **WHEN** 配置缺失、凭据无效或提供方不可达
- **THEN** 系统 MUST 明确失败或停留在 fixture 模式
- **AND** MUST NOT 把 fixture 输出标注为真实模型结果
- **AND** MUST NOT 回退到其他模型供应商

### Requirement: 模型输出必须通过结构化校验

模型 SHALL 只返回预定义 Schema 的结构化结果；字段缺失、枚举越界或类型不符时 MUST 判定为失败或按既有规则降级，MUST NOT 把未校验文本当作答案发布。

#### Scenario: 输出合法

- **WHEN** 模型返回符合 Answer Schema 的结构化结果
- **THEN** 系统 MUST 继续执行既有的引用与支持关系复核
- **AND** MUST NOT 因模型置信度而跳过复核

#### Scenario: 输出不合法

- **WHEN** 模型返回的字段缺失、类型错误或引用不存在的证据 ID
- **THEN** 该次生成 MUST 被判失败
- **AND** 回答 MUST NOT 以部分结果发布
- **AND** 运行 MUST 记录可供排查的错误代码

### Requirement: 模型不具备工具、网络与写入能力

模型调用 SHALL 只接收任务所需的最小上下文，MUST NOT 提供工具、任意 URL 抓取、文件写入或执行能力；检索与外部访问 MUST 只由服务端端口完成。

#### Scenario: 生成回答

- **WHEN** 服务端调用模型撰写答案
- **THEN** 请求 MUST 只包含问题、证据包与必要指令
- **AND** MUST NOT 包含数据库凭据、内部 URL 或可执行工具描述
- **AND** 模型 MUST NOT 能发起新的检索

#### Scenario: 网页内容包含指令

- **WHEN** 作为证据的网页片段包含“忽略之前指令”之类的注入内容
- **THEN** 系统 MUST 把它当作不可信资料
- **AND** MUST NOT 因此改变权限、调用工具或泄露其他内容

### Requirement: 模型调用可追溯且受运行预算约束

每次模型调用 SHALL 记录提供方、模型版本、任务类型与耗时，并 MUST 服从运行的截止时间；超时 MUST 以超时结束，MUST NOT 发布未完成的结果。

#### Scenario: 截止时间到达

- **WHEN** 模型调用超过运行剩余时间
- **THEN** 运行 MUST 以 `timed_out` 结束
- **AND** MUST NOT 发布部分答案

#### Scenario: 用量记录

- **WHEN** 一次运行完成
- **THEN** 审计 MUST 记录提供方、模型版本、任务类型与耗时
- **AND** MUST NOT 记录完整提示词中的客户内容