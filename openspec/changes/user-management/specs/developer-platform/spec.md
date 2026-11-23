# Spec Delta

## Purpose

定义开发者能力：组织/部门范围的 API Key 生命周期、Key 认证的主体与权限边界、每次请求的日志记录，以及只读的用量/日志面板。

## ADDED Requirements

### Requirement: API Key MUST 只在创建时显示一次

系统 SHALL 生成高熵 API Key，并仅在创建响应中返回一次原文；服务端 MUST 只保存哈希与可展示前缀；Key SHALL 支持名称、scopes、可选过期时间、last_used 与撤销。

#### Scenario: 创建后无法再次读取原文

- **WHEN** 管理员创建 API Key 并刷新页面
- **THEN** 列表只显示前缀与元数据，不显示完整 Key

#### Scenario: 撤销立即生效

- **WHEN** 管理员撤销某个 API Key
- **THEN** 使用该 Key 的后续请求立即返回 401

### Requirement: Key 认证 MUST 受 Key 范围与创建者权限约束

使用 `Authorization: Bearer <key>` 的请求 SHALL 解析为该组织/部门范围的服务主体；Key 的 scopes MUST NOT 超出创建者授予时所拥有的权限；越权请求 MUST 返回 403。

#### Scenario: 部门 Key 不越界

- **WHEN** 一个属于 Legal 部门的 Key 请求 Finance 文档
- **THEN** 请求被拒绝

#### Scenario: 创建者权限被收窄

- **WHEN** 创建者失去某权限后，其 Key 仍尝试该操作
- **THEN** 请求被拒绝，Key 不继承创建者的历史权限

### Requirement: Key 请求 MUST 记录日志

每次使用 API Key 的请求 SHALL 记录 Key ID、组织、方法、路径、状态码、耗时与时间；日志 MUST NOT 保存请求体、响应体、文档正文或任何令牌原文。

#### Scenario: 成功与失败都记录

- **WHEN** Key 请求返回 200 或 4xx
- **THEN** 均产生一条请求日志，状态码可区分

#### Scenario: 日志不含敏感内容

- **WHEN** 检查任意请求日志
- **THEN** 不包含 Key 原文、密码或文档正文

### Requirement: Developer 页面 MUST 需要授权

Developer 页面与 API Key/日志接口 SHALL 要求 `developer.manage` 权限；无权用户 MUST NOT 看到 Key 前缀列表或日志摘要。

#### Scenario: 普通成员访问 Developer

- **WHEN** 只有 `member` 角色的用户打开 Developer
- **THEN** 返回 403 或空态提示无权访问

### Requirement: 用量面板 MUST 支持按时间与 Key 聚合

系统 SHALL 提供只读用量视图，至少支持按天、Key 与状态码聚合请求数；列表 SHALL 支持分页与时间范围筛选。

#### Scenario: 按天查看用量

- **WHEN** 管理员选择最近 7 天
- **THEN** 返回按天与 Key 聚合的请求数，不返回请求正文

### Requirement: Webhook MUST NOT 在首版提供

首版 MUST NOT 暴露 Webhook 配置、密钥或投递日志；相关 UI 入口 MUST 说明“暂未提供”，避免用户误以为已生效。

#### Scenario: Developer 页面无 Webhook

- **WHEN** 用户打开 Developer
- **THEN** 只看到 API Keys 与请求日志/用量，没有可用的 Webhook 配置