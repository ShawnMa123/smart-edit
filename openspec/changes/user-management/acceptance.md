# PG 模式验收记录（task 9.3）

- 日期：2026-11-19
- 环境：本机 + `ssh -f -N team04-pg`（`127.0.0.1:15432 -> RDS/team04`），`SMART_EDIT_AUTH_MODE=pg`
- 数据库：`team04`（迁移到 `schema_version=3`，17 张身份/权限/活动/开发者表）
- 可复现命令：`.venv/bin/python -m pytest tests/test_identity_acceptance.py -q`（PG 不可达时该用例自动 skip）
- 认证方式：真实 HttpOnly 会话 cookie；写请求带 `X-Requested-With: smart-edit`

## 验收路径与实测结果

| # | 动作 | 请求 | 实测结果 |
| --- | --- | --- | --- |
| 1 | 注册组织管理员 | `POST /auth/register` | `201`；`Set-Cookie: smart_edit_session=…; HttpOnly; SameSite=lax`；响应体不含原始 token |
| 2 | 建组织/部门 | `POST /organizations/{id}/departments` × Legal、Finance | `201`；闭包写入 Legal→Legal、Finance→Finance |
| 3 | 建部门文档并加锁 | `POST /documents`（`department_id`）+ `POST …/lock` | `201`；活动事件写入 `document created` / `document locked` |
| 4 | 邀请成员 | `POST /organizations/{id}/invites` | `201`；响应含一次性 `invite_token` 与 `accept_path`，不含 `token_hash` |
| 5 | 接受邀请 | `POST /invites/accept` | `200`；成员状态 active，部门角色 assignment 生效；二次接受返回 `409 invite_used` |
| 6 | 跨部门读取 | Finance 成员 `GET /documents/{legal_doc}` | `403 FORBIDDEN`，响应不含标题/正文 |
| 7 | 同部门读取 | Finance 成员 `GET /documents/{finance_doc}` | `200` |
| 8 | 活动可见性 | Finance 成员 `GET /activity?org_id=…` | `document locked` 仅返回 Finance 文档；Legal 事件不可见；`unread_count >= 1` |
| 9 | 创建 API Key | `POST /developer/organizations/{id}/keys`（Finance 范围） | `201`；仅此响应含 `sk_live_…` 原文，列表只有前缀 |
| 10 | Key 越界 | `GET /documents/{legal_doc}` + `Authorization: Bearer` | `403` |
| 11 | Key 同部门 | `GET /documents/{finance_doc}` + Bearer | `200` |
| 12 | 请求日志 | `GET /developer/organizations/{id}/request-logs` | `total >= 2`；字段仅 `method/path/status/latency_ms/key_id/created_at`，无 body/令牌 |
| 13 | 撤销 Key | `DELETE …/keys/{id}` 后再请求 | `401 AUTH_REQUIRED` |

## 启动日志（节选）

```
identity mode=pg target=127.0.0.1:15432/team04 pool=1-8 session_ttl=604800s
pg migrations applied: 001_identity.sql, 002_organization.sql, 003_collaboration.sql
```

## 断线场景

隧道关闭后以 `SMART_EDIT_AUTH_MODE=pg` 启动：

```
DatabaseUnavailable: PostgreSQL identity is enabled but 127.0.0.1:15432/team04 is not reachable.
Start the tunnel (ssh -f -N team04-pg), check SMART_EDIT_DATABASE_URL, or set SMART_EDIT_AUTH_MODE=fake
for a local demo. No fallback identity was started.
```

进程直接失败，没有回退到 `X-Demo-User`。

## 未包含（v1 明确不做）

邮件投递、邮箱验证、自助找回密码、SSO/OIDC、Webhook、文档/助手数据迁移到 PG。