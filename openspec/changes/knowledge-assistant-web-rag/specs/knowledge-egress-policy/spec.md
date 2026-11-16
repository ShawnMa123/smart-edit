# Spec Delta

## Purpose

定义知识助手在任何外部调用（检索或模型）之前必须完成的内容判定：只能外发最小化且被允许的查询，禁止外发文档正文、选区、实体与会话身份；判定为失败关闭，决定与理由必须可审计、可向用户解释。

## ADDED Requirements

### Requirement: 任何外部调用之前必须通过出站闸门

系统 SHALL 在发起联网检索或外部模型调用之前执行出站判定；闸门不可用时 MUST 按拒绝处理，MUST NOT 以“先发出去再判断”的方式绕过。

#### Scenario: 闸门不可用

- **WHEN** 出站策略服务缺失、超时或抛错
- **THEN** 外部调用 MUST NOT 发出
- **AND** 运行 MUST 以可解释的失败或降级结束
- **AND** MUST NOT 退化为“默认允许”

#### Scenario: 未开启联网

- **WHEN** 用户没有开启联网
- **THEN** 系统 MUST NOT 为该次运行调用联网层
- **AND** 出站闸门 MUST 仍记录本次无需外发

### Requirement: 出站内容最小化且禁止字段不出站

外发内容 SHALL 只包含完成检索所必需的查询文本与被允许的检索参数；文档正文、选区原文、附件内容、结构化实体值与会话身份 MUST NOT 出现在任何外部请求中。

#### Scenario: 问题包含文档原文

- **WHEN** 用户的问题中粘贴了文档正文或选中片段
- **THEN** 系统 MUST 判定为拒绝或改写，MUST NOT 原文外发
- **AND** 用户 MUST 看到被拦截或被改写的原因

#### Scenario: 问题包含实体值

- **WHEN** 问题包含金额、对手方名称、保函/合同编号或账号等被标记为敏感的实体
- **THEN** 外发查询 MUST 移除这些实体或拒绝外发
- **AND** MUST NOT 通过分词、翻译或模型改写的方式间接外发

#### Scenario: 会话身份

- **WHEN** 构造任何外部请求
- **THEN** 请求 MUST NOT 携带用户标识、租户标识与会话标识
- **AND** MUST NOT 在查询文本中拼接这些值

### Requirement: 出站判定只有允许、改写与拒绝三档且理由可见

系统 SHALL 把判定结果表达为 `allow | redact | deny`，并在拒绝或改写时向用户说明原因；MUST NOT 把拒绝展示为“未检索到结果”。

#### Scenario: 允许

- **WHEN** 查询只包含通用问题与可公开的规则标识
- **THEN** 判定为 `allow`
- **AND** 实际外发文本 MUST 与展示给用户的“将发送内容”一致

#### Scenario: 改写后允许

- **WHEN** 查询可以去掉敏感实体后仍然成立
- **THEN** 判定为 `redact` 并给出改写后的查询
- **AND** 用户 MUST 能在外发前看到改写结果

#### Scenario: 拒绝

- **WHEN** 查询包含不可外发的文档内容或高敏标识
- **THEN** 判定为 `deny`
- **AND** 回答 MUST 说明未执行联网检索及其原因
- **AND** MUST NOT 用本地结果冒充联网结果

### Requirement: 出站决定与实际外发内容必须可审计

每次出站 SHALL 记录判定结果、理由代码、提供方与实际外发查询（或不可逆摘要），并在联网轮次中以脱敏形式保存历史消息。

#### Scenario: 审计事件

- **WHEN** 一次运行完成外发判定
- **THEN** 审计 MUST 记录 `egress_allowed` 或 `egress_blocked` 及理由
- **AND** 记录 MUST 包含请求关联 ID 与运行 ID
- **AND** MUST NOT 记录文档正文或完整敏感实体

#### Scenario: 历史消息展示

- **WHEN** 用户在历史会话中查看一条联网轮次
- **THEN** 显示的问句 MUST 是实际外发的版本或明确标注为已脱敏
- **AND** MUST NOT 回显被禁止外发的原文

### Requirement: 准入清单与判定规则可配置且变更留痕

允许的域名、禁止字段与判定规则 SHALL 通过配置维护，变更 MUST 可追溯；缺失或损坏的配置 MUST 视为最严格策略。

#### Scenario: 配置缺失

- **WHEN** 准入域名清单缺失或无法解析
- **THEN** 所有联网请求 MUST 被拒绝
- **AND** MUST NOT 回退到“允许全部域名”

#### Scenario: 规则变更

- **WHEN** 管理员更新准入域名或禁止字段
- **THEN** 变更 MUST 记录变更人、时间与差异
- **AND** 正在运行的请求 MUST 继续使用其启动时的策略版本