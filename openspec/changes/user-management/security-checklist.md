# 安全清单（task 9.2）

| 项 | 实现 | 验证 |
| --- | --- | --- |
| 会话 cookie | `HttpOnly`、`SameSite=Lax`、`Path=/`；生产 `SMART_EDIT_AUTH_COOKIE_SECURE=1` 时 `Secure` | 任务 2.2 / `tests/test_identity_auth.py::test_register_sets_httponly_cookie_and_me` |
| 会话令牌 | 高熵 `secrets.token_urlsafe(32)`；DB 只存 SHA-256；绝对过期 + `revoked_at` | 同上 + `test_logout_revokes_session_and_logout_all` |
| 密码 | argon2id（参数可调）；DB 只有哈希；接口/日志不回显 | `test_password_hash_is_argon2id_and_verifies`、登录失败用例 |
| 登录限流 | 同 IP + 邮箱窗口计数，超阈值 `429 RATE_LIMITED`，文案不区分账号存在性 | `test_login_failures_are_rate_limited`、`test_login_rejects_wrong_password_and_unknown_email_identically` |
| CSRF | 写方法必须带 `X-Requested-With: smart-edit`（或同源 Origin）；API Key 请求免 CSRF | `test_write_without_csrf_header_is_rejected` |
| 401 | 无/失效会话直接 401，不回退默认用户；`AUTH_MODE=pg` 忽略 `X-Demo-User` | `test_unauthenticated_requests_return_401` |
| 403 不泄露存在性 | 不可见资源统一 `403 FORBIDDEN`，不含标题/正文 | `test_department_documents_are_isolated_and_org_documents_are_shared` |
| 邀请令牌 | 只存哈希、一次性、默认 72h、邮箱匹配、不得越权授予 | `test_invite_is_single_use`、`test_department_admin_is_scoped_and_cannot_escape` |
| API Key | 只存哈希、仅创建时显示一次、前缀展示、撤销立即 401、scopes ∩ 创建者当前权限 | `test_api_key_is_shown_once_logged_and_revoked`、`test_api_key_scopes_and_creator_permissions_are_intersected` |
| 请求日志 | 只记 method/path/status/latency/key_id；无 body/令牌/正文 | `test_api_key_is_shown_once_logged_and_revoked` 字段集合断言 |
| 活动载荷 | 关键字过滤（password/token/secret/content/body/text/key/authorization/cookie）；只保留标量与短列表 | `test_activity_payload_never_contains_sensitive_content` |
| 授权版本 | 成员/角色/部门变更递增 `organizations.authorization_version`；旧上下文 409 | `test_automation_applicability_rejects_a_stale_authorization_version`、`bump_authorization_version` 单测调用点 |
| 最后管理员 | 拒绝移除/停用最后一名有效 `org_admin` | `test_last_org_admin_cannot_be_removed` |
| 失败关闭 | PG 不可达启动即失败，明确提示且不回退假身份 | `test_unreachable_pg_fails_at_startup_with_actionable_message` |
| 日志抽查 | 启动/请求日志只含 mode、target（host:port/db）、状态与 request id；不打印密码/令牌/DSN 密码 | `_safe_target()` 只取 host/port/dbname；单测断言错误信息不含密码 |

## 日志边界说明

- `DatabaseUnavailable` 的消息只包含 `host:port/database` 与修复建议，不包含连接串中的用户名/密码。
- 登录失败、邀请、Key 校验的错误文案统一，不区分“账号不存在/密码错误/Key 已撤销”。
- Activity `detail_json` 在写入前过滤敏感键；正文类字段即使误传也不会落库。