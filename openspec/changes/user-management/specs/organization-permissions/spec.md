# Spec Delta

## Purpose

定义多组织与部门层级下的成员、角色与资源授权：部门闭包、仅允许的继承语义、组织级与部门级资源的可见性，以及所有 API 的统一授权边界。

## ADDED Requirements

### Requirement: 组织与部门 MUST 支持层级结构

系统 SHALL 支持多组织；每个组织 SHALL 拥有部门树（`parent_id`），并维护祖先-后代闭包以支持继承查询；一个账号 MAY 同时属于多个组织。

#### Scenario: 创建子部门

- **WHEN** 管理员在 Legal 下创建 Contracts
- **THEN** Contracts 成为 Legal 的子部门，闭包记录 Legal -> Contracts

#### Scenario: 多组织成员

- **WHEN** 用户同时属于 Org A 与 Org B
- **THEN** 该用户在两个组织分别拥有成员身份，权限不互相合并

### Requirement: 角色 MUST 按范围分配并仅允许继承

角色分配 SHALL 挂在组织或部门范围上；生效权限 MUST 为该组织范围内的角色与该资源部门祖先链上角色的并集；系统 MUST NOT 支持显式 deny，收权 SHALL 通过删除分配完成。

#### Scenario: 部门管理员

- **WHEN** 用户被授予 `dept_admin` 于 Legal
- **THEN** 该用户对 Legal 及其子部门拥有管理权限，对 Finance 无权限

#### Scenario: 没有拒绝例外

- **WHEN** 用户同时拥有 org 级与部门级角色
- **THEN** 权限为两者并集，不存在“某部门被拒绝”的配置

### Requirement: 资源 MUST 支持组织级与部门级范围

文档、活动事件与 API Key SHALL 可标记为组织级（`department_id` 为空）或部门级；组织级文档 SHALL 对该组织所有 active member 可读，部门级文档 SHALL 仅对祖先链上拥有 `document.read` 的用户可读。

#### Scenario: 组织级文档

- **WHEN** 普通成员读取 `department_id` 为空的文档
- **THEN** 读取允许

#### Scenario: 部门级文档隔离

- **WHEN** Finance 成员读取 Legal/Contracts 的文档
- **THEN** 请求被拒绝（403），且不泄露文档标题或内容

### Requirement: 所有业务 API MUST 执行统一授权

每个读取或修改资源的 API SHALL 调用统一授权判定 `authorize(actor, action, resource_scope)`；MUST NOT 仅凭客户端提交的 `workspace_id`、`department_id` 或角色字段放行。

#### Scenario: 客户端伪造部门

- **WHEN** 请求体携带用户无权访问的 `department_id`
- **THEN** 服务端以会话与角色判定为准，拒绝该请求

#### Scenario: 未授权与不存在不可区分

- **WHEN** 用户访问无权资源
- **THEN** 返回 403；对不可见资源不得返回其存在性细节

### Requirement: 助手证据 MUST 按文档范围过滤

助手检索、引用与 AI 上下文 SHALL 只使用当前用户可见的文档范围；MUST NOT 把其他部门或组织的文档内容带入回答、引用或摘要。

#### Scenario: 跨部门提问

- **WHEN** Legal 成员向助手提问，而知识证据只存在于 Finance 私有文档
- **THEN** 该证据不进入上下文，回答说明未找到可见证据

### Requirement: 邀请 MUST 使用一次性令牌且不得越权授予

邀请 SHALL 绑定组织、可选部门、邮箱、角色、邀请人与过期时间；令牌 MUST 只存哈希、单次消费；邀请人 MUST NOT 授予自己无权管理的角色。v1 MAY 不发送邮件，改为由管理员复制的链接。

#### Scenario: 邀请被重复使用

- **WHEN** 已接受的邀请链接被再次打开
- **THEN** 不创建第二个成员身份，返回已失效提示

#### Scenario: 越权邀请

- **WHEN** 部门管理员尝试邀请 `org_admin`
- **THEN** 邀请被拒绝

### Requirement: 组织 MUST 保留至少一名有效管理员

系统 SHALL 阻止移除或停用最后一名有效 `org_admin`；恢复/移交 MUST 走受控流程，MUST NOT 允许普通成员自行接管。

#### Scenario: 移除最后管理员

- **WHEN** 管理员尝试移除组织中最后一名有效 `org_admin`
- **THEN** 操作被拒绝并提示先指定新的管理员