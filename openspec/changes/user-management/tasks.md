# Tasks

## 1. PG 地基与依赖

- [x] 1.1 增加 `psycopg[binary]`、`argon2-cffi` 依赖，并确认 `pyproject.toml` 安装成功；PG 连接串沿用 `SMART_EDIT_DATABASE_URL`。验证：`.venv/bin/pip install -e .` 后能导入 `psycopg` 与 `argon2`
- [x] 1.2 新增 PG 迁移目录与最小迁移执行器（编号 SQL + `schema_meta` 版本校验），创建 users/sessions/organizations/departments/department_closure/memberships/roles/role_permissions/role_assignments 表。验证：空库执行迁移后表存在，重复执行幂等
- [x] 1.3 增加 PG 连接池与启动健康检查；未配置或不可达时**明确失败**，不回退 SQLite 身份。验证：断开隧道启动报错包含可操作提示
- [x] 1.4 `AssistantSettings` 增加 `AUTH_MODE=fake|pg`（默认 fake），并透传到服务构造。验证：设置单测覆盖默认值与非法值

## 2. 认证核心

- [x] 2.1 argon2id 哈希与校验模块（参数可配置，密码永不落日志）。验证：单测覆盖正确/错误密码与哈希格式
- [x] 2.2 注册与登录：邮箱唯一、通用失败文案、登录成功创建会话并写 HttpOnly cookie（SameSite=Lax，生产 Secure）。验证：API 测试覆盖成功、错误密码、未知邮箱、cookie 属性
- [x] 2.3 `/auth/me`、登出、登出全部设备；会话 token 只存哈希、绝对过期与撤销。验证：API 测试覆盖会话撤销后 401
- [x] 2.4 登录限流（IP+邮箱）与 CSRF 校验（SameSite + 写操作 Origin/自定义头）。验证：限流测试与缺少 CSRF 头的写请求被拒绝
- [x] 2.5 认证依赖：pg 模式从 cookie 解析 Principal（user, active_org），忽略 `X-Demo-User`；fake 模式保持现有行为。验证：两种模式各一条 API 测试；现有测试在 fake 模式下全绿

## 3. 组织与部门

- [x] 3.1 组织 CRUD 与多组织成员关系；`workspace_id = org_id`，seed `ws_demo_01` 演示组织承接历史数据。验证：迁移/seed 后旧数据仍可读
- [x] 3.2 部门树 CRUD + 闭包维护（增/删/移动在事务内完成，提供闭包重建脚本）。验证：单测覆盖移动子树后的祖先查询
- [x] 3.3 会话活动组织切换：服务端重新校验成员状态，失败不切换。验证：API 测试覆盖非成员切换被拒

## 4. 成员、角色与邀请

- [x] 4.1 角色目录与权限表（org_admin/dept_admin/member/auditor + 权限清单），成员邀请/移除/停用。验证：单测覆盖角色权限映射
- [x] 4.2 角色分配 API：org 级与部门级 assignment、仅允许继承的生效权限查询（闭包 + 并集）。验证：单测覆盖 org admin、dept admin、跨部门不可见
- [x] 4.3 邀请：一次性 token（只存哈希、默认 72h）、角色不得超越邀请人权限、重复消费被拒；v1 返回可复制链接、不发邮件。验证：API 测试覆盖接受一次成功、二次失败、越权邀请被拒
- [x] 4.4 最后一名有效 org_admin 不可移除/停用。验证：单测覆盖拒绝与允许（存在第二名管理员）

## 5. 统一授权与资源范围

- [x] 5.1 `AuthorizationService.authorize(actor, action, scope)` + 权限目录；按请求缓存查询结果。验证：单测覆盖动作/范围矩阵
- [x] 5.2 SQLite 迁移：`documents`、`document_drafts`、`automation_proposals` 增加 `department_id`（可空），旧数据为 NULL。验证：迁移脚本幂等，旧数据读取不变
- [x] 5.3 逐路由接入授权（列出 30 条路由覆盖清单）：文档读/写/锁/提交/导出、自动化、助手、组织/成员、活动、开发者。验证：每条路由至少一条 403 用例；fake 模式回归全绿
- [x] 5.4 助手证据过滤：本地/RAG/法规/web 证据在合成前按文档 scope 过滤；切换组织后旧 run 不得继续。验证：跨部门提问测试断言证据被剔除
- [x] 5.5 自动化授权版本：移除 `auth-demo-1` 硬编码，成员/角色变更递增版本，旧上下文返回 409。验证：单测覆盖版本失效

## 6. 前端认证与 People

- [x] 6.1 前端 API 客户端统一 `credentials: 'include'` + CSRF 头；新增 `AuthProvider`、`/login`、未登录重定向与登出。验证：组件测试覆盖未登录跳转、登录成功、登出
- [x] 6.2 顶部组织/部门切换器；`DEFAULT_WORKSPACE` 改为 `active_org.workspace_id`，KnowledgePanel 等调用点同步。验证：切换组织后请求携带新 workspace；组件测试通过
- [x] 6.3 People 页面接真 API：部门树、成员列表、角色抽屉（继承角色只读）、邀请链接复制；`?demo=1` 回退演示数据。验证：组件测试覆盖树渲染、邀请复制、无权限空态

## 7. Activity

- [x] 7.1 服务端事件写入：登录/登出、组织/部门、成员/角色、文档提交/锁、助手 run、API Key 变更；载荷不含正文/令牌。验证：单测断言事件字段与敏感内容缺失
- [x] 7.2 Activity 查询 API：可见性（org/dept）、`scope=all|my_department`、`unread`、游标分页、Mark one/all read。验证：API 测试覆盖跨部门不可见、两个用户已读互不影响
- [x] 7.3 Activity UI 替换 demo：服务端列表、筛选、未读计数、Mark all read；成员移除后主体显示“已移除”。验证：组件测试通过

## 8. Developer

- [x] 8.1 API Key 创建/撤销：高熵、只存哈希、前缀展示、scopes、可选过期、last_used；创建响应只显示一次原文。验证：API 测试覆盖创建后列表无原文、撤销后 401
- [x] 8.2 Key 认证：`Authorization: Bearer` 映射服务主体，scopes 与资源 scope 取交集；创建者失权后 Key 不继承历史权限。验证：单测覆盖部门越界与创建者收权
- [x] 8.3 请求日志中间件与用量 API：记录 method/path/status/latency/key_id，不记录 body；按天/Key/状态聚合。验证：单测断言日志无敏感内容，聚合结果正确
- [x] 8.4 Developer UI：Key 列表/创建一次性展示/撤销、请求日志与用量；`developer.manage` 保护；Webhook 明确“暂未提供”。验证：组件测试覆盖无权访问与创建流程

## 9. 文档、安全与回归

- [x] 9.1 更新 `README.md` / `how_to_use.md`：PG 依赖与迁移、`AUTH_MODE`、角色与继承规则、邀请 v1（无邮件）、API Key、部门级资源规则与限制。验证：按文档从零启动一次，登录与 People 可用
- [x] 9.2 安全清单：cookie 属性、CSRF、登录限流、密码/令牌/API Key 不入日志、403 不泄露资源存在性。验证：对应单测 + 日志抽查
- [x] 9.3 PG 模式验收：登录 → 建组织/部门 → 邀请成员 → 跨部门访问被拒 → 活动可见性 → 创建 Key 并产生请求日志。验证：验收记录（run/请求/日志）写入 change 目录
- [x] 9.4 回归：`.venv/bin/python -m pytest tests -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate user-management --strict`；fake 模式与 pg 模式各跑一次关键路径。验证：四条命令通过

## Workflow follow-up

- 评审通过后归档本 change；归档前确认 PG 隧道与 `team04` 库可用，并在部署文档写明 `AUTH_MODE=pg` 的启用步骤。