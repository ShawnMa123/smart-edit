# Spec Delta

## Purpose

定义本地账号认证与会话行为：PG 中的用户与密码、argon2id 哈希、服务端会话 cookie、登录限流、登出与会话撤销，以及测试/本地可用的假身份模式边界。

## ADDED Requirements

### Requirement: 登录 MUST 使用 PG 本地账号与 argon2id

系统 SHALL 在 PG 中保存用户邮箱与密码哈希，密码 MUST 使用 argon2id 哈希；MUST NOT 保存或记录明文密码。

#### Scenario: 正确凭据登录

- **WHEN** 用户提交已注册邮箱与正确密码
- **THEN** 系统创建服务端会话并返回 HttpOnly 会话 cookie

#### Scenario: 错误凭据不泄露账号是否存在

- **WHEN** 用户提交不存在邮箱或错误密码
- **THEN** 系统返回同一条通用失败文案，且不创建会话

### Requirement: 会话 MUST 为服务端不透明令牌

系统 SHALL 生成高熵随机会话令牌，仅在服务端保存其哈希；cookie MUST 设置 `HttpOnly` 与 `SameSite=Lax`，生产环境 MUST 设置 `Secure`；会话 SHALL 有绝对过期时间与撤销时间。

#### Scenario: 令牌不可从数据库还原

- **WHEN** 读取 `sessions` 表
- **THEN** 只能看到令牌哈希，看不到可用于登录的原始令牌

#### Scenario: 登出撤销当前会话

- **WHEN** 用户调用登出
- **THEN** 当前会话被标记撤销，后续带该 cookie 的请求返回 401

#### Scenario: 登出全部设备

- **WHEN** 用户选择登出全部设备
- **THEN** 该用户所有未撤销会话失效

### Requirement: 未认证请求 MUST 返回 401

真实认证模式下，除登录/注册/健康检查外的 API SHALL 要求有效会话；缺失或失效会话 MUST 返回 401，且 MUST NOT 回退到默认用户。

#### Scenario: 无 cookie 访问受保护接口

- **WHEN** 未携带会话 cookie 请求文档或助手接口
- **THEN** 返回 401，不返回任何业务数据

#### Scenario: 假身份模式仅限显式配置

- **WHEN** `AUTH_MODE=fake`
- **THEN** 允许使用 `X-Demo-User` 测试头；当 `AUTH_MODE=pg` 时该头 MUST 被忽略

### Requirement: 登录失败 MUST 限流

系统 SHALL 对同一 IP 与邮箱组合的连续失败请求限流，超过阈值后返回可重试的明确错误，且不得因此暴露账号存在性。

#### Scenario: 连续失败被限制

- **WHEN** 同一 IP 与邮箱在短时间内连续登录失败超过阈值
- **THEN** 后续尝试在冷却期内被拒绝，并提示稍后重试

### Requirement: 会话 MUST 绑定活动组织

会话 SHALL 记录活动组织；切换组织 MUST 在服务端重新校验成员状态，失败时 MUST NOT 切换。

#### Scenario: 只有成员身份才能切换

- **WHEN** 用户尝试切换到不属于自己的组织
- **THEN** 切换被拒绝，会话保持原活动组织

### Requirement: 权限变更 MUST 使旧上下文失效

成员、角色或部门归属变更时，系统 SHALL 推进该组织的授权版本；携带旧版本的会话或自动化上下文 MUST 被拒绝并要求重新加载。

#### Scenario: 角色被撤销后的旧请求

- **WHEN** 管理员撤销某成员的角色，而该成员用旧授权版本发起自动化请求
- **THEN** 请求返回冲突/失效错误，而不是继续使用旧权限

### Requirement: 敏感凭据 MUST NOT 进入日志

密码、会话令牌、邀请令牌与 API Key MUST NOT 出现在日志、审计载荷或错误响应中。

#### Scenario: 登录与 API Key 审计

- **WHEN** 登录或创建 API Key 产生审计记录
- **THEN** 载荷只包含事件类型、主体与结果，不包含密码或原始令牌