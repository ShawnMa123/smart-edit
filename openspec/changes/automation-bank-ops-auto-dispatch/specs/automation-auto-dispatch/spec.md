# Spec Delta

## Purpose

定义"一次配置、同类文档自动投递"的后台能力：以模板绑定判定同类文档，以规则决定下游与档位，
在终审通过后按已批准的 submission 快照自动组包投递，并给出可追溯的交付状态与人工兜底入口。

## ADDED Requirements

### Requirement: 模板绑定是同类文档的唯一判据

文档 SHALL 记录 `template_id`（精确版本）与 `template_name`（业务类型）。通过模板套用创建文档时
MUST 自动写入绑定；未绑定模板的文档 MUST NOT 参与自动投递；授权用户 MUST 能显式绑定或改绑历史文档，
且每次绑定/改绑都要留下审计。

#### Scenario: 套用模板创建文档后自动绑定
- **WHEN** 授权用户用模板 T 生成一份新文档
- **THEN** 该文档记录 T 的 `template_id` 与 `template_name`
- **AND** 后续该文档终审通过时可被 T 对应的规则命中

#### Scenario: 未绑定文档不自动发送
- **WHEN** 一份没有模板绑定的文档走到终审通过
- **THEN** 系统不创建投递任务
- **AND** 运行记录给出 `skipped: no_binding` 的原因

#### Scenario: 历史文档可显式绑定
- **WHEN** 授权用户为一份已存在文档指定模板
- **THEN** 绑定被保存并写入审计（操作者、文档、模板）

### Requirement: 规则以模板业务类型指向下游

规则 SHALL 至少包含 `template_name`、`connector_id`、`trigger`、`mode`、`required`、`priority`
与作用域字段。多条启用规则可以同时命中同一模板，系统 MUST 为每条规则独立创建任务；
同一 `submission` 下同一 `connector_id` MUST 只发送一次，重复规则 MUST 给出可见告警而不是重复外发。

#### Scenario: 一个模板配置多个下游
- **WHEN** 模板 T 有两条启用规则，分别指向下游 A 与 B
- **THEN** T 的文档终审通过后创建两个投递任务
- **AND** 两个下游各收到一次请求

#### Scenario: 重复下游被去重
- **WHEN** 同一模板的两条规则指向同一个下游连接器
- **THEN** 系统只创建/执行一次该下游的投递
- **AND** 规则列表提示该连接器被重复配置

### Requirement: 终审通过触发自动投递

系统 SHALL 在审批事件 `approval.second.approve` 且审批状态为 `approved` 后创建投递任务；
MUST NOT 在审批事务内发起下游 HTTP 调用；MUST 使用该次审批对应的 submission 快照组包，
MUST NOT 读取审批之后可能继续变化的草稿。

#### Scenario: 二审通过自动入队
- **WHEN** 二审批准一份已绑定模板且命中规则的文档
- **THEN** 系统写入一条 `queued` 投递任务并关联 `submission_id`
- **AND** 审批请求本身只做数据库写入，不发起外发

#### Scenario: 退回或拒绝不触发
- **WHEN** 审批结果为 `return` 或 `reject`
- **THEN** 系统不创建投递任务

#### Scenario: 使用审批快照组包
- **WHEN** 文档在终审通过后被继续编辑成新的草稿版本
- **THEN** 自动投递仍使用已批准 submission 的文本与变量组包

### Requirement: 多下游交付状态与 sent 的定义

系统 SHALL 为每个下游分别记录任务结果，并聚合成文档级交付状态。`sent` MUST 表示"所有被标记为
required 的下游均已成功投递"；部分成功 MUST 显示 `partial`，任一 required 下游失败 MUST 显示
`needs_attention`；只有 shadow 运行时 MUST 显示 `shadowed`。

#### Scenario: 全部下游成功
- **WHEN** 三个 required 下游任务都返回成功
- **THEN** 文档交付状态为 `sent`
- **AND** 每个下游都有一条回执

#### Scenario: 部分下游失败
- **WHEN** 两个 required 下游成功、一个失败
- **THEN** 文档交付状态为 `needs_attention`
- **AND** 详情里同时展示成功与失败的下游行

#### Scenario: 可选下游失败不阻断
- **WHEN** 所有 required 下游成功，一个 optional 下游失败
- **THEN** 文档交付状态保持 `sent`，失败只作为告警展示

### Requirement: 默认 shadow 与显式升级

新规则 MUST 默认使用 `shadow`：只组包并记录"将要发送"的结果，MUST NOT 发起下游 HTTP 调用，
MUST NOT 写 dispatch 回执。档位升级与降级 MUST 由授权用户显式操作并写审计；
全局 kill switch 关闭时，所有 `auto_send` 规则 MUST 降级为 `shadow`。

#### Scenario: 新规则不直接外发
- **WHEN** 新建规则并让其第一次命中终审通过的文档
- **THEN** 任务记录 `would_send` 与请求体摘要
- **AND** 下游没有收到请求，回执表没有新增行

#### Scenario: 关闭总开关后不再自动发送
- **WHEN** 全局自动发送开关被关闭
- **THEN** 原本 `auto_send` 的规则只产生 shadow 结果
- **AND** 面板提示自动发送已被全局停用

#### Scenario: 升级档位留痕
- **WHEN** 授权用户把规则从 `shadow` 升级为 `needs_review` 或 `auto_send`
- **THEN** 规则档位更新，审计记录操作者与前后档位

### Requirement: 幂等与重试边界

每个投递任务 MUST 使用 `auto:{rule_id}:{submission_id}` 作为幂等键，同一任务重放 MUST NOT
产生第二次外发。5xx 与超时 MUST 退避重试且不超过配置次数；4xx、白名单拒绝、密钥缺失与
请求体不满足契约 MUST NOT 重试，直接进入人工处理状态。

#### Scenario: 重放不重复发送
- **WHEN** 同一规则与同一 submission 的投递被重复调度
- **THEN** 系统返回既有回执，下游只收到一次请求

#### Scenario: 5xx 重试
- **WHEN** 下游第一次返回 500
- **THEN** 任务进入退避等待并按计划重试
- **AND** 成功后状态变为 `sent`

#### Scenario: 请求体不合格不重试
- **WHEN** 下游返回 409 或本地检测到 `missing_required_body`
- **THEN** 任务直接进入 `needs_attention`
- **AND** 不进行自动重试

### Requirement: 人工兜底与运行可见性

`needs_review` 档位的任务 SHALL 可由授权用户在运行面板放行；失败任务 SHALL 可重试、取消或忽略。
文档 MUST 暴露交付状态与每个下游的结果；被跳过的文档 MUST 给出可读原因（无规则、未绑定、规则停用）。

#### Scenario: 放行待复核任务
- **WHEN** 授权用户在运行面板放行一条 `needs_review` 任务
- **THEN** 系统以同一幂等键执行发送
- **AND** 任务与文档交付状态同步更新

#### Scenario: 跳过原因可读
- **WHEN** 终审通过的文档没有命中任何启用规则
- **THEN** 文档交付状态为 `not_configured`
- **AND** 运行记录显示 `skipped: no_rule`

### Requirement: 自动投递全程可追溯

每个任务的状态迁移 SHALL 被记录；发送回执 MUST 关联 `job_id`、`rule_id`、`submission_id` 与实际使用的
`template_id`；自动请求的操作者 MUST 标记为系统身份，MUST NOT 伪装成具体用户。

#### Scenario: 回执可回溯到规则与审批稿
- **WHEN** 一条自动任务发送成功
- **THEN** 回执同时带有任务 id、规则 id、submission id 与模板 id
- **AND** 审计里记录的请求者标识为系统自动化身份

#### Scenario: 状态迁移可查看
- **WHEN** 用户打开任务详情
- **THEN** 可以看到从入队到最终状态的时间线（含每次重试与失败原因）