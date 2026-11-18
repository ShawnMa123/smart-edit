# Spec Delta

## Purpose

定义知识助手对外的部署能力视图：模型与处理器是否就绪、三条证据层是否可用、出站策略版本，以及网关是否声明支持只读搜索工具；让前端可以据此决定开关是否可用，而不是让用户猜测。

## ADDED Requirements

### Requirement: 能力端点返回部署能力且不泄露密钥

系统 SHALL 提供 `GET /assistant/capabilities`，返回模型是否配置、处理器是否已批准、local / approved_web / general_web 三层是否可用、出站策略版本与准入域名数量。响应 MUST NOT 包含 API key、endpoint 明文或任何用户标识。

#### Scenario: 全部未配置

- **WHEN** 部署没有配置模型、也没有配置任何 web provider
- **THEN** 响应 MUST 把 `model.configured` 与三层能力都标为 `false`
- **AND** MUST NOT 用“未知”代替确定的不支持

#### Scenario: 通用联网可用

- **WHEN** 模型已配置、处理器已批准且通用联网已开启
- **THEN** 响应的 `layers.general_web` MUST 为 `true`
- **AND** `model.label` MUST 返回提供方标签（如 `doubao:<model>`）

#### Scenario: 不泄露敏感配置

- **WHEN** 任意身份调用该端点
- **THEN** 响应 MUST NOT 包含密钥、完整 endpoint 或用户/工作区标识
- **AND** MUST 只返回布尔值、版本字符串与计数

### Requirement: 搜索工具能力由网关声明

系统 SHALL 通过网关自身的只读能力标志判断能否使用 `web_search` 工具；MUST NOT 依赖具体提供方类名。未声明该标志的实现 MUST 被视为不支持。

#### Scenario: 支持搜索工具的网关

- **WHEN** 网关声明 `supports_tool_search = true`
- **THEN** 通用联网路由 MAY 生效（仍需满足其余条件）

#### Scenario: 未声明或声明为否

- **WHEN** 网关没有声明该标志，或声明为 `false`
- **THEN** 通用联网 MUST NOT 被调用
- **AND** 运行 MUST 继续走既有标准路径

### Requirement: 能力缺失时必须报告为不可用而不是静默降级

任何一项能力缺失 SHALL 在能力响应中明确为 `false`，并给出可用于解释的原因码；MUST NOT 在缺少能力时假装已启用。

#### Scenario: 缺少自建 web provider

- **WHEN** `approved_web` 层不可用
- **THEN** 响应 MUST 把该层标为 `false`
- **AND** 前端 MUST 能据此把对应的联网开关设为不可用