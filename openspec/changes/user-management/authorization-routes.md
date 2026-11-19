# 路由授权覆盖清单（task 5.3）

`AUTH_MODE=fake` 保留原有 `X-Demo-User` / capability 行为；`AUTH_MODE=pg` 下每条业务路由都在
`Principal` 解析后执行 `AuthorizationService.authorize(...)` 或 `DocumentAccess.authorize(...)`。
资源 scope 一律来自服务端存储（SQLite `documents.department_id` / 组织成员关系），客户端传参只作目标。

## 文档（`app/api/documents.py`）

| 路由 | 权限 | 备注 |
| --- | --- | --- |
| `POST /documents` | `document.create` | 目标部门必须在当前组织；`department_id` 只作目标 |
| `GET /documents/{id}` | `document.read` | 组织级：active member；部门级：祖先链 |
| `GET /documents/{id}/drafts/{draft_id}` | `document.read` | 同上 |
| `PUT /documents/{id}/drafts/{draft_id}` | `document.edit` | 仍校验锁/fencing token |
| `PATCH /documents/{id}/drafts/{draft_id}/variables` | `document.edit` | 同上 |
| `POST /documents/{id}/drafts/{draft_id}/checkpoints/{ckpt}/restore` | `document.edit` | 回滚也是写操作 |
| `POST /documents/{id}/drafts/{draft_id}/lock` | `document.lock` | 记录 Activity |
| `POST /documents/{id}/locks/{lock_id}/heartbeat` | `document.lock` | 只有锁持有者续租 |
| `POST /documents/{id}/locks/{lock_id}/release` | `document.lock` | 只有锁持有者释放 |

## 自动化（`app/api/automation.py`）

| 路由 | 权限 | 备注 |
| --- | --- | --- |
| `POST /automation/runs` | `document.edit` + `automation.use` | 创建时把 authorization version 写入依赖 |
| `GET /automation/runs` | `document.read` | 只返回可见文档的 run |
| `GET /automation/runs/{id}` | `document.read` | |
| `POST /automation/runs/{id}/cancel` | `document.read` | 取消不改变草稿 |
| `GET /automation/results/{id}` | `document.read` | |
| `GET /automation/proposals/{id}` | `document.read` | |
| `POST /automation/proposals/{id}/decisions` | `document.edit` | 决策需要写权限 |
| `POST /automation/proposals/{id}/apply` | `document.edit` + 锁 | 版本过期/授权版本变化返回 409 |
| `POST /automation/applications/{id}/undo` | `document.edit` + 锁 | |
| `GET /automation/applications/{id}` | `document.read` | |

## 助手（`app/api/assistant.py`）

| 路由 | 权限 | 备注 |
| --- | --- | --- |
| `GET /assistant/capabilities` | `assistant.use` | 无业务数据 |
| `POST /assistant/snapshots` | `assistant.use` | 只存本人 workspace 的文本 |
| `POST /assistant/sessions` | `assistant.use` | workspace 必须匹配 active org |
| `GET /assistant/sessions` | `assistant.use` | |
| `GET /assistant/sessions/{id}` | `assistant.use` | 会话绑定 org + user |
| `POST /assistant/sessions/{id}/runs` | `assistant.use` | 证据在合成前按文档 scope 过滤 |
| `GET /assistant/runs/{id}` | `assistant.use` | |
| `POST /assistant/runs/{id}/cancel` | `assistant.use` | |
| `GET /assistant/sessions/{id}/messages` | `assistant.use` | |
| `GET /assistant/messages/{id}/citations/{cid}` | `assistant.use` | 引用必须指向可见文档 |
| `PUT /assistant/messages/{id}/feedback` | `assistant.use` | |

## 组织 / 成员 / 邀请 / 活动 / 开发者（新增）

| 路由组 | 权限 |
| --- | --- |
| `GET /organizations*` | active member（列表只返回本人组织） |
| `POST/PATCH/DELETE /organizations*` | `org.manage` |
| `GET /organizations/{id}/departments` | active member |
| `POST/PATCH/DELETE .../departments*` | `department.manage`（父/目标部门 scope） |
| `GET .../members` | active member |
| `PATCH .../members/{user_id}` | `member.manage` + 最后一名 `org_admin` 保护 |
| role-assignments | `role.manage` + 授予者权限必须覆盖目标角色 |
| invites | `invite.manage` + 授予者权限必须覆盖目标角色 |
| `POST /invites/accept` | 已登录且邮箱匹配 |
| `GET /activity*` | active member（部门事件按 `activity.read` 祖先链过滤） |
| `POST /activity/*/read`、`/read-all` | 同上，已读按用户独立 |
| `/developer/*` | `developer.manage`；API Key 认证时 scopes ∩ 创建者当前权限 |