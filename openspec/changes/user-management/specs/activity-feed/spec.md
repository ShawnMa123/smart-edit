# Spec Delta

## Purpose

定义服务端活动流：哪些行为会产生事件、事件按组织/部门范围如何可见、每个用户的已读/未读状态，以及列表筛选与敏感内容边界。

## ADDED Requirements

### Requirement: 关键行为 MUST 记录为服务端事件

系统 SHALL 在服务端记录登录/登出、组织与部门变更、成员与角色变更、文档创建/提交/锁、助手运行完成、API Key 创建/撤销等事件；事件 MUST 包含组织、可选部门、事件类型、动作、主体与资源引用。

#### Scenario: 提交版本产生事件

- **WHEN** 用户提交文档版本
- **THEN** 产生一条包含组织、部门、主体与文档引用的活动事件

#### Scenario: 事件不依赖浏览器

- **WHEN** 用户清除浏览器存储或更换设备
- **THEN** 活动流仍从服务端返回

### Requirement: 活动可见性 MUST 与资源范围一致

组织级事件 SHALL 对该组织 active member 可见；部门级事件 SHALL 仅对祖先链上拥有 `activity.read` 的用户可见；MUST NOT 向无权用户返回事件内容或资源标题。

#### Scenario: 部门事件隔离

- **WHEN** Finance 成员请求活动流
- **THEN** 不返回 Legal 部门的事件

#### Scenario: 组织管理员查看全部

- **WHEN** `org_admin` 请求活动流
- **THEN** 可见该组织全部范围的事件

### Requirement: 已读状态 MUST 按用户保存

每个用户 SHALL 拥有独立的活动已读状态；系统 SHALL 支持将单条或全部可见事件标记为已读；未读计数 MUST 与筛选条件一致。

#### Scenario: 两个用户各自已读

- **WHEN** 用户 A 标记某事件已读
- **THEN** 用户 B 的同一事件仍未读

#### Scenario: 标记全部已读

- **WHEN** 用户点击“全部标为已读”
- **THEN** 仅其当前可见范围内的事件被标记为已读

### Requirement: 活动列表 MUST 支持范围与状态筛选

活动接口 SHALL 支持“全部 / 我的部门 / 仅未读”筛选与分页，并按时间倒序返回；响应 SHALL 包含总数或下一页游标。

#### Scenario: 仅未读筛选

- **WHEN** 用户选择“仅未读”
- **THEN** 只返回该用户未读且可见的事件

#### Scenario: 分页稳定

- **WHEN** 在分页期间新增事件
- **THEN** 已返回页不重复、不跳过（按游标或稳定的时间+ID 排序）

### Requirement: 活动事件 MUST NOT 包含敏感内容

事件载荷 MUST NOT 包含文档正文、选中文本、密码、会话令牌、邀请令牌或 API Key 原文；只 SHALL 保存可审计的引用与摘要。

#### Scenario: 文档事件载荷

- **WHEN** 记录文档提交事件
- **THEN** 载荷只包含文档 ID、版本与主体，不包含正文内容

### Requirement: 成员移除后历史事件 MUST 保留

成员被移除或停用后，其历史活动事件 SHALL 保留给仍有权查看的管理员；事件的主体 MUST 显示为已移除用户，而不是被静默删除。

#### Scenario: 移除成员后的历史

- **WHEN** 管理员移除某成员
- **THEN** 该成员的历史事件仍可见，主体标记为已移除