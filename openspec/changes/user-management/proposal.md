# Proposal

## Why

当前 People / Activity / Developer 都是演示界面，身份来自 `X-Demo-User`，没有真实账号、组织、部门、角色与会话；`SMART_EDIT_DATABASE_URL` 虽指向 PG，但仓库既没有连接依赖也没有任何表。要让文档、审批、AI 助手真正按“组织 → 部门 → 成员”隔离，必须先有一套可登录、可授权、可审计的用户管理体系。

## What Changes

- **PG 本地认证**：`users / sessions`；密码 `argon2id`；登录后签发 HttpOnly 会话 cookie（服务端只存 token 哈希），支持登出与登出全部设备；登录限流；`AUTH_MODE=fake|pg` 保留测试/本地无 PG 模式。
- **组织与部门**：`organizations`、`departments`（树）+ `department_closure`；一个账号可属于多个组织；登录后选定活动组织与部门上下文。
- **成员与角色**：`memberships`、`roles / role_permissions / role_assignments`；**仅允许（additive）继承**——角色只在授予范围及子树生效，无 deny，收权即删除 assignment。
- **资源范围（Option B）**：文档、活动事件、API Key 可属于组织或部门；组织级资源对所有 active member 可读，部门级资源按“祖先部门角色”授权；`documents` 增加 `department_id`（可空）。
- **统一授权**：新增 `authorize(principal, action, resource_scope)`，覆盖现有 30 条 API；助手检索与证据按部门范围过滤；自动化中硬编码的 `auth-demo-1` 改为真实授权版本，权限变更即失效。
- **Activity**：服务端 `activity_events` + 按用户的 `activity_reads`；覆盖登录、组织/成员/角色变更、文档提交/锁、助手 run、API Key 变更；支持全部/我的部门/仅未读。
- **Developer**：`api_keys`（argon2/哈希存储、前缀、scopes、last_used、撤销）与 `request_logs`/用量面板；**不做 Webhook**。
- **前端**：登录页与 `AuthProvider`；People 部门树 + 成员/角色抽屉；Activity/Developer 接真 API；`DEFAULT_WORKSPACE` 改为 `active_org.workspace_id`；顶部组织/部门切换器。
- **BREAKING**：
  - 真实模式下必须登录；`X-Demo-User` 仅在 `AUTH_MODE=fake` 可用。
  - `workspace_id` 的语义从“固定演示空间”变为“组织 ID”；现有数据以 seed 组织 `ws_demo_01` 承接。
  - 未授权请求返回 `401/403`；权限变更会让现有会话/自动化上下文失效。
- **明确不做（本轮）**：邮件发送、邮箱验证、自助找回密码（v1 由管理员重置/复制邀请链接）、SSO/OIDC、Webhook、把文档/助手数据迁移到 PG。

## Capabilities

### New Capabilities

- `identity-auth`: PG 本地账号、密码哈希、会话 cookie、登录/登出/限流与 `AUTH_MODE` 行为。
- `organization-permissions`: 多组织、部门树、闭包继承、成员与角色分配、资源范围（组织级/部门级）与统一授权。
- `activity-feed`: 服务端活动事件、可见性、按用户已读/未读与筛选。
- `developer-platform`: API Key 生命周期、scopes、请求日志与用量视图。

### Modified Capabilities

<!-- 无：`openspec/specs/` 下只有 document-editor / document-import / rich-text-editing；
     文档与助手的授权变化属于新能力，不在既有 spec 中写 MODIFIED delta。 -->

## Impact

- **后端依赖**：新增 `psycopg`、`argon2-cffi`（及可能的 `email-validator`）；PG 连接串沿用 `SMART_EDIT_DATABASE_URL`。
- **后端模块**：新增 auth/org/permissions/activity/developer 服务与 API；`documents`、`assistant`、`automation` 的读取路径加授权；`adapters.FakeIdentity` 替换为可切换的 PG identity。
- **数据库**：PG 新建身份/权限/活动/API Key 表；SQLite 的 `documents*`、`automation_proposals` 增加 `department_id`；`ws_demo_01` seed 为演示组织。
- **前端**：登录页、AuthProvider、People/Activity/Developer 三个页面重写；请求统一 `credentials: include` + CSRF 头。
- **安全/运维**：cookie 安全属性、CSRF、登录限流、密码哈希参数、API Key 只存哈希、审计；PG 隧道（`15432`）与库可用性需在实施前确认。
- **测试**：认证与授权单测、`AUTH_MODE=fake` 回归（现有 750+ 测试保持通过）、跨部门隔离与继承的 API/UI 测试。