# Design

## Context

- 现有 Automation 是 workspace 作用域的服务端能力：`automation_templates` / `automation_connectors` /
  `automation_mappings` / `automation_dispatches`（`app/documents/store.py`），入口在
  `AssistantPanel` 的第四个 tab，没有任何权限过滤。
- 鉴权是"权限名"模型：角色目录在 `app/identity/permissions.py`，服务通过
  `Principal.has(capability)` 判定，capability 与权限名在 `app/identity/principal.py` 映射
  （`apply → automation.apply`）。角色与部门作用域由 `AuthorizationService` 按
  org / department 祖先链求并集。
- 审批状态机在 `app/documents/store.py`：`draft → pending_first → pending_second → approved /
  returned / rejected`；`decide_approval` 在同一事务内写 `host_audit` 并 `_enqueue("approval.{stage}.{decision}")`。
  `outbox_events` 已有 `delivered_at` 列，但没有消费者。
- dispatch 已具备真实外发、白名单、环境变量密钥、超时与回执；`automation_dispatches` 上已有
  `(workspace_id, idempotency_key)` 唯一索引。
- 约束：SQLite 单写者（`BEGIN IMMEDIATE`），部署是单 systemd 服务单 worker（`deploy/README.md`）；
  文档与模板当前没有关联字段。
- 动机见 `proposal.md`；行为契约见 `specs/automation-access-control` 与 `specs/automation-auto-dispatch`。

## Goals / Non-Goals

**Goals:**

- 用权限名（而不是角色名或 UI 开关）表达 Automation 的可见 / 配置 / 发送 / 审计边界。
- 让部门管理员的配置权严格限制在本部门，组织级配置只由 `bank_ops` / `org_admin` 管理。
- 让"终审通过 → 自动投递多下游"成为可恢复、可重放、可审计的异步入队流程，而不是审批事务里的同步调用。
- 在默认 `shadow` 档位下，规则可以"零外发"地验证组包结果。

**Non-Goals:**

- 不修改审批状态机，不新增 `sent` 审批状态；`sent` 是交付状态。
- 不重写 `automation-template-registry` 的模板/连接器/映射/回执能力。
- 不做规则的可视化流程编排（多步骤、条件分支、等待人工节点）。
- 不做外部系统回调驱动的"已签收"语义（本期 `sent` 只代表请求已成功被下游接受）。

## Decisions

### D1 权限：新增细粒度权限，旧 scope 只降级为只读/发送

新增 `automation.view` / `automation.configure` / `automation.dispatch` / `automation.audit`，
并在 `principal._CAPABILITY_PERMISSIONS` 增加对应 capability；`/automation` 路由用统一 dependency
按能力判权，方法内保留 `_require` 做纵深防御。

**理由**：现有 `apply` 同时服务"提案应用"和"下游发送"，继续复用它无法区分"改配置"和"发一次请求"。
**备选**：把 `automation.apply` 直接收归 `bank_ops`（会让既有 API Key 与企业集成立即失效，且提案 apply
语义被牵连）；按角色名判权（违反仓库"只判权限名"的既有设计）。

### D2 部门作用域：资源带 `department_id`，复用既有 scope 继承

`automation_templates` / `automation_connectors` / `automation_rules` 增加 `department_id`；
`NULL` 表示组织级。`dept_admin` 只能写本部门行；读组织级 + 本部门（含祖先）行。
`bank_ops` / `org_admin` 可写组织级与部门级。

**理由**：与 `AuthorizationService` 的 scope 合并规则一致，不需要新造一套 ACL。
**备选**：只做 workspace 级（`dept_admin` 实际能改全组织，不符合确认口径）；为部门复制一套资源（数据冗余、
模板版本漂移）。

### D3 同类文档：文档绑定精确模板，规则按 `template_name` 匹配

`documents` 增加 `template_id` + `template_name`（或等价绑定表）。模板套用创建文档时写入；
历史文档由授权用户显式绑定。规则只绑定 `template_name`；发送时使用**文档自己的** `template_id`。

**理由**：模板会以同名递增版本（`automation_templates` 的 `(workspace, name, version)` 唯一约束）。
若规则绑定 `template_id`，新版本会让老规则静默失配；绑定 `template_name` 并让文档携带自己的版本，
既能让老规则继续生效，也不会把 v2 模板套到 v1 文档上。
**备选**：规则绑定 `template_id` + 显式升级（会让"新版本上线"变成一次必须的人工迁移）；标题/关键词匹配
（不稳定、难解释）；AI 相似度（不可审计，不符合本仓库"建议不落库"的原则）。

### D4 触发：消费 outbox 的 `approval.second.approve`，审批事务只入队

审批决定提交后，worker 读取未消费的 `approval.second.approve`（`delivered_at IS NULL`），
按 `submission_id` 组装任务。审批事务内只写 `outbox_events` 与 job，不发 HTTP。

**理由**：审批事务短、可回滚；HTTP 失败不会把审批结果回滚，也不会让用户等待网络。
**备选**：在 `decide_approval` 里同步外发（事务被网络绑定、失败要定义"审批成功但发送失败"的语义）；
定时轮询全表（无法保证"终审即触发"，延迟不可控）。

### D5 任务模型：每个 `(rule, submission)` 一条 job，多下游 fan-out

`automation_jobs` 以 `(workspace_id, idempotency_key)` 唯一，键为 `auto:{rule_id}:{submission_id}`；
同一 submission 下同一 `connector_id` 去重。`required` 与 `optional` 区分聚合语义：
required 全成功才算文档级 `sent`，否则 `needs_attention` / `partial`。

**理由**：每条下游独立重试、独立回执、独立可见；聚合状态能表达"部分成功"。
**备选**：一条 job 里循环多个下游（重试粒度粗，一条失败就整条重放，容易重复发送已成功目标）；
first-match-wins（无法满足"一个文档多个下游"的确认口径）。

### D6 档位：默认 `shadow`，显式升级，全局 kill switch

规则 `mode ∈ {shadow, needs_review, auto_send}`，新规则默认 `shadow`。`shadow` 复用
`preview()` 只组包不发送，不写回执。升级由授权用户显式操作并审计；全局开关关闭时，
`auto_send` 在运行时降级为 `shadow`。

**理由**：自动外发不可逆，先把"会发什么"变成可观察事实；档位升级是治理动作而不是配置副作用。
**备选**：新规则默认 `auto_send`（误发成本过高）；按"连续成功 N 次自动升级"（难以审计责任，且失败样本
可能不足以证明安全）。

### D7 组包使用审批快照，不复用读草稿的 dispatch 路径

自动任务通过 submission 的 `text` / `content_json` 组包（新增内部 `prepare_from_text` 或允许传入
预组 `values`），并把 `submission_id` 写入任务与回执。现有 `dispatch()` 仍按 `document_id` 读草稿，
仅用于人工通道。

**理由**：审批通过后草稿可能继续被编辑成下一版；读草稿会把"未批准的改动"发给下游。
**备选**：审批时冻结 draft（影响现有协作流程）；在 dispatch 里加 `snapshot` 分支但共用同一方法
（容易误用，且人工通道需要实时草稿语义）。

### D8 运行载体：独立单实例 worker + 补偿扫描

新增 `automation-worker`（systemd unit 或 `python -m app.automation.worker`），单实例串行消费 outbox，
并按 `next_attempt_at` 扫描到期任务。重试退避 1m / 5m / 30m（最多 3 次）；4xx / 白名单拒绝 /
`missing_required_body` 不重试。

**理由**：SQLite 单写者与现有部署形态一致；串行避免同一 submission 的并发写。
**备选**：FastAPI `BackgroundTasks`（进程重启丢任务）；多 worker（SQLite 写冲突）；Celery/Redis
（新增外部依赖，与当前单机部署不匹配）。

### D9 命名与兼容

新接口用 `/automation/jobs`、`/automation/rules`；遗留 `/automation/runs`（proposal run）保持不动。
`automation_dispatches` 只增列（`job_id/rule_id/trigger/submission_id`），老回执这些列为空。

**理由**：避免与既有 `automation_runs`（assistant/proposal 运行）语义冲突；增列迁移可回滚。

## Risks / Trade-offs

- [误发/重发] → 默认 `shadow`、`(workspace, idempotency_key)` 唯一、同 connector 去重、全局 kill switch。
- [审批后草稿被改导致错发] → 只用 submission 快照组包，回执记录 `submission_id`。
- [新模板版本让规则静默失配] → 规则按 `template_name` 匹配；Setup 显示"有规则但无命中"与"已绑定无规则"。
- [部门作用域漏判] → 所有写路径统一走 `AuthorizationService.authorize(action, ResourceScope)`，
  列表查询按组织级 + 部门祖先链过滤，并补部门矩阵测试。
- [权限收口破坏演示/集成] → fake 身份保持全能力；旧 API Key scope 映射为 view/dispatch；
  DEMO 脚本改用 Bank Ops 账号；403 文案明确角色要求。
- [SQLite 单写者 + 任务积压] → worker 单实例、批量上限、`(status, next_attempt_at)` 索引；
  未来迁移 PG 时用 `FOR UPDATE SKIP LOCKED`。
- [规则重复配置同一 connector] → 不阻断保存（可能是有意的双规则），但去重发送 + 面板告警。
- [规则语义变更无法回溯到当时版本] → 本期记录 `rule_id` 与状态迁移时间线；若审计要求"规则快照"，
  后续增加 `rule_versions`（见 Open Questions）。

## Migration Plan

1. **Schema（向后兼容）**：`SCHEMA_VERSION` 递增；新增三张表与索引；`documents` / `automation_dispatches`
   仅加列。老数据默认未绑定模板、无 job 关联，不影响既有模板/连接器/回执读取。
2. **权限（先收口、后放开自动）**：先上线权限与 UI gating（P0），确认 `bank_ops` / `org_admin` /
   `dept_admin` 正常、其他角色 403；此阶段不启用任何自动发送。
3. **规则（shadow 观察）**：上线规则 CRUD 与 `shadow` 运行；Bank Ops 对真实模板建立规则并观察。
4. **Worker（默认关闭）**：worker unit 先以 `SMART_EDIT_AUTOMATION_WORKER=0` 部署；
   开启后规则仍默认 `shadow`，由 Bank Ops 逐条升级。
5. **回滚**：关闭 worker unit 与全局 kill switch → 所有规则只 shadow；schema 增列/新表保留，
   `automation_dispatches.job_id` 为空的回执仍可读。
6. **文档**：更新 `README.md` / `DEMO.md` / `DEMO_automation.md`，说明新的角色入口与自动投递流程。

## Open Questions

- 是否需要规则版本快照（每次修改保留历史版本，供审计回放"当时为什么发"）；本期用
  `rule_id + job_events + payload hash` 记录，若合规要求"规则全文快照"再补。
- 是否需要按下游单独配置并发/超时/熔断；本期沿用 `connector.timeout_seconds` 与串行 worker。
- 文档交付状态变化是否需要实时通知（Activity 推送 vs 轮询）；本期先写 Activity 事件，推送频率可后续调整。