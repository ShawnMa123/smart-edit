# Design

## Context

动机见 `proposal.md` — Why。塑造本设计的仓库事实（均已核实）：

- **身份是假的**：`app/assistant/adapters.py` 的 `FakeIdentity` 从 `X-Demo-User` 取用户（默认 `user_demo_01`），`workspace_id` 固定为 `DEFAULT_WORKSPACE = "ws_demo_01"`；`FakeAuthorization` 只校验 workspace 相等。
- **授权面很薄**：`AuthorizationPort.resolve()` 只在 `AssistantService` 内调用；文档、自动化等 API 主要靠 `workspace_id + owner_user_id`，没有统一 `authorize()`。应用共约 30 条路由。
- **自动化有硬编码**：`automation/service.py` 在发布与 run 校验中比较 `authorization_version == "auth-demo-1"`，必须改为真实版本。
- **数据在 SQLite**：`documents`、`document_drafts`、`document_checkpoints`、`document_locks`、`automation_proposals` 都只有 `workspace_id`/`owner_user_id`，没有部门；助手数据同样只有 workspace。
- **PG 未接入**：`.env` 有 `SMART_EDIT_DATABASE_URL=postgresql://...@127.0.0.1:15432/team04`，但 `pyproject.toml` 没有 `psycopg`，`15432` 隧道当前未开，仓库里没有任何 PG 表。
- **前端是演示**：`DemoPeopleDialog`/`DemoActivityPanel` 读 `demoData`，`Developer` 实际是 `ImplementationMap`，`Identity` 显示“Authentication is not configured”；`DEFAULT_WORKSPACE` 在 `assistantTypes.ts` 写死。
- **需求文档**：`tradeAI_requirementDesign_v2/Requirements.md` 3.1–3.4 有 AUTH/ORG/UM/INV 的企业级条目；Activity 与 Developer 没有现成条目。

## Goals / Non-Goals

**Goals:**

- 一次登录后，所有请求以真实 `Principal(user, active_org, active_department)` 执行。
- 组织/部门/角色/继承在 PG 中可查询、可审计、可测试；资源按 Option B 隔离。
- Activity 与 Developer 使用服务端数据，替换演示实现。
- 保持 `AUTH_MODE=fake` 时现有 750+ 测试与本地演示可运行。

**Non-Goals:**

- 不发邮件、不做邮箱验证/自助找回密码/SSO/OIDC（v1 由管理员重置与复制邀请链接）。
- 不把文档/助手数据迁到 PG；`workspace_id` 仍是字符串关联键。
- 不做 Webhook、不做跨组织共享、不做资源级 ACL（多部门共享）。
- 不做企业级审批矩阵或 ABAC。

## Decisions

### D1 · PG 本地认证与会话

`users(id, email unique, password_hash, display_name, status, created_at)`；密码用 argon2id。登录成功创建 `sessions(id, user_id, token_hash, active_org_id, expires_at, revoked_at, user_agent, ip)`；cookie 保存原始 token（`HttpOnly; SameSite=Lax; Secure(prod)`），服务端只存 SHA-256。

- 备选：JWT —— 否决：撤销/登出全部设备/权限版本失效都需要服务端状态，PG 会话更直接。
- 备选：bcrypt —— 否决：新系统用 argon2id，参数可随硬件升级。

### D2 · 多组织 + 部门树 + 闭包

`organizations`、`departments(org_id, parent_id)`、`department_closure(ancestor, descendant, depth)`；组织本身视为根（查询时同时带上 org 级角色）。

- `workspace_id = org_id`。部门不是独立 workspace，避免复制文档/助手/锁的隔离键。
- 会话保存 `active_org_id`（可选 `active_department_id` 仅作 UI 上下文）；切换组织必须重新校验 `memberships.status='active'`。

### D3 · 仅允许继承：角色挂在范围上

```
roles(key, name, scope_level)
role_permissions(role_key, permission)
role_assignments(user_id, scope_type, scope_id, role_key, granted_by, created_at)
```

生效权限 = org 级分配 + 资源部门祖先链上的部门级分配，取并集；没有 deny 表。

- 备选：把角色直接放 membership —— 否决：无法表达“同一人在 Legal 是 admin、在 Finance 只是 member”。
- 初始角色：`org_admin`、`dept_admin`、`member`、`auditor`。`developer.manage` 是 org 级权限，不单设角色。

### D4 · Option B 资源范围

`documents.department_id`、`document_drafts.department_id`、`automation_proposals.department_id` 增加可空列；`NULL` = 组织级。

```
can_read(user, doc):
    if doc.department_id is None: return active_member(user, doc.org)
    return has_perm(user, "document.read", doc.department_id)
```

组织级文档对成员可读；部门级文档只对祖先链上有 `document.read` 的人可读。写入/锁/提交/导出分别要求 `document.edit/lock/share/export`。

- 备选：文档必须归部门 —— 否决：现有共享文档与助手证据需要组织级默认。
- 备选：多部门共享/ACL —— 否决：首版复杂度不可控。

### D5 · 统一授权层与版本

新增 `AuthorizationService.authorize(principal, action, scope)`；在 API 依赖中解析 Principal 后调用。权限判定使用 PG 查询（闭包 + 角色），结果按请求上下文缓存。

- 所有资源接口必须传真实资源 scope；客户端提交的 `workspace_id/department_id/role` 只作为“目标”，不作为授权依据。
- `authorization_version`：每次成员/角色/部门归属变更时递增组织版本并写入会话上下文；自动化与助手在长任务中比较版本，过期返回 409。
- 未授权：无权资源返回 403；对不可见资源不暴露存在性。

### D6 · 助手与文档的跨部门隔离

助手会话仍绑定 `org + user`；检索（本地/RAG/法规/web）得到的证据在进入合成前按文档 scope 过滤；引用必须指向用户可见文档。切换组织后旧会话/旧 run 不得在新组织上下文继续执行。

### D7 · Activity 事件与已读

`activity_events(id, org_id, department_id, actor_user_id, kind, action, resource_type, resource_id, detail, created_at)` + `activity_reads(user_id, event_id, read_at)`。

- 事件由服务端在领域动作后写入（auth/org/member/role/document/assistant/api-key），不依赖浏览器。
- 可见性复用 D4：组织级事件对成员可见；部门级事件要求祖先链 `activity.read`。
- 列表支持 `scope=all|my_department`、`unread=true`、游标分页；载荷不含正文/令牌。
- 成员移除后事件保留，主体显示为已移除。

### D8 · Developer：API Key + 请求日志

`api_keys(id, org_id, department_id, name, key_hash, prefix, scopes, created_by, expires_at, last_used_at, revoked_at)`；`api_request_logs(id, api_key_id, org_id, method, path, status, latency_ms, created_at)`。

- Key 只在创建时显示一次；服务端存哈希与 8–12 位前缀；认证走 `Authorization: Bearer`，映射为带 scope 的服务主体。
- Key 的 scopes 与资源 scope 取交集；创建者失权后 Key 不继承历史权限。
- 日志只记方法/路径/状态/耗时，不记 body/正文/令牌；用量面板按天+Key+状态聚合。
- 不做 Webhook（页面明确“暂未提供”）。

### D9 · 前端认证与页面

- 新增 `/login` 页面与 `AuthProvider`；启动时 `GET /auth/me`，未认证跳转登录。
- 顶部组织/部门切换器；切换后重新加载资源与助手会话。
- People：部门树 + 成员列表 + 邀请链接复制 + 角色抽屉（继承角色只读展示）。
- Activity：服务端列表 + 全部/我的部门/仅未读 + Mark all read。
- Developer：Key 列表 + 创建（一次性展示）+ 请求日志/用量。
- `DEFAULT_WORKSPACE` 改为 `active_org.workspace_id`；`?demo=1` 可回退演示数据一个版本。

### D10 · 依赖、迁移与测试模式

- 新增 `psycopg[binary]`、`argon2-cffi`；PG 连接串沿用 `SMART_EDIT_DATABASE_URL`。
- PG schema 用编号 SQL 迁移（`migrations/001_identity.sql` …）并在启动时校验版本；SQLite 的 `documents*`/`automation_proposals` 用现有 `schema_meta` 版本升级加 `department_id`。
- `AUTH_MODE=fake|pg`：fake 保留 `X-Demo-User` 与固定 workspace，供现有测试与无 PG 环境；pg 模式忽略该头。
- 现有 `ws_demo_01` seed 为一个演示组织，历史数据继续可见。

### D11 · 邀请与账号恢复的 v1 边界

邀请生成一次性 token（只存哈希，默认 72h），管理员复制链接；接受时校验邮箱、角色与邀请人当前权限。v1 不发送邮件、不做邮箱验证；密码找回由管理员重置。此边界在文档与 UI 明确标注。

### D12 · 安全基线

- argon2id 参数可配置；登录/邀请/Key 校验统一限流；错误文案不区分账号是否存在。
- CSRF：SameSite=Lax + 写操作校验 `Origin`/自定义头；生产 cookie `Secure`。
- 密码、会话/邀请/API Key 原文不得进入日志、审计与错误响应。

## Risks / Trade-offs

- [企业级范围过大] → 一个 change 内按阶段交付（D1–D4 为地基，D7/D8 后置）；每阶段可独立验收，但 change 不拆。
- [全 API 授权是行为破坏] → `AUTH_MODE=fake` 保留回归；pg 模式新增 401/403 合约测试；逐路由迁移并列出覆盖清单。
- [PG 单点与隧道依赖] → 连接池 + 启动健康检查；未配置 PG 时明确失败，不回退 SQLite 身份。
- [闭包表一致性] → 部门增删移动在事务内维护闭包；提供重建闭包的维护脚本。
- [跨部门 AI 泄漏] → 证据在合成前过滤，而不是仅靠 UI 隐藏；测试覆盖跨部门提问。
- [旧数据 workspace 迁移] → seed 组织承接 `ws_demo_01`；不做批量重写，文档默认 `department_id=NULL`。
- [Key/邀请令牌泄漏] → 只存哈希、一次性显示、审计不含原文。

## Migration Plan

1. PG 依赖/迁移/连接池 + `AUTH_MODE` 开关；启动兼容 fake 模式。
2. 账号/会话/组织/部门/成员/角色 API 与 People UI；seed 演示组织。
3. 文档加 `department_id` + 统一 `authorize()` + 助手证据过滤；更新自动化版本校验。
4. Activity 事件/已读 + UI。
5. Developer API Key + 请求日志/用量 + UI。
6. 回归与验收；回滚：`AUTH_MODE=fake` 恢复演示身份，PG 表保留不影响现有数据。

## Open Questions

- 活动事件保留期限与清理策略（先按 180 天，待定）。
- API Key scopes 的最终清单（先复用权限目录的子集）。
- 部门级 AI 上下文：是“当前部门 + 组织级文档”，还是允许用户显式切换部门范围（先按前者）。
- 邮箱验证/自助找回密码的引入时间（v1 明确不做）。
- PG 的备份/高可用责任方（部署侧）。