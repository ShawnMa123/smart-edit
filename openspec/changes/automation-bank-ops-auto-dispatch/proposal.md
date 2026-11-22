# Proposal

## Why

Automation 目前是"人人可见、申请人可配置"的前台面板，与"银行后台运营能力"的定位不符：
`applicant` / `member` 持有 `automation.apply`，可以建连接器并向真实下游发请求，而真正负责运营的
`bank_ops` 反而没有配置权。

同时，配置好的模板与下游只能靠人逐单点击 `Send`：审批终审通过后到下游入账之间依赖人工操作，
既会漏发，也无法把"同类文档"复用到后续单据。需要把这条链路变成**一次配置、终审后自动投递**，
并且失败可追溯、可人工兜底。

## What Changes

- **BREAKING**：Automation 模块只对 `bank_ops`、`org_admin`、`dept_admin`（仅本部门）开放；
  `applicant` / `member` 不再看到入口，也不能调用 `/automation/*`；`compliance` 只读。
- 新增细粒度权限 `automation.view` / `automation.configure` / `automation.dispatch` /
  `automation.audit`；后端统一 dependency 鉴权，前端按权限过滤 tab、拦截深链，无权限时给出明确说明。
- 模板、连接器、规则增加 `department_id`（`NULL` = 组织级）；`dept_admin` 只能创建/修改本部门行，
  可只读使用组织级行；`bank_ops` / `org_admin` 管理组织级。
- 文档新增模板绑定（`template_id` + `template_name`）：模板套用创建文档时自动绑定；历史/导入文档由
  Bank Ops 显式绑定；未绑定文档不参与自动投递。
- 新增 `automation_rules`：Bank Ops 配置"某类模板（`template_name`）→ 某下游连接器 + 触发时机 + 档位"，
  一次配置长期生效。
- 新增 job 与 worker：监听终审通过事件 `approval.second.approve`（已有 outbox 事件），自动按
  submission 快照组包并投递；**支持多下游 fan-out**（一个文档命中多条规则 → 并行/串行投递多个下游）。
- 幂等键 `auto:{rule_id}:{submission_id}` 复用 dispatch 唯一索引；5xx/timeout 退避重试，
  4xx / 白名单拒绝不重试；失败进入人工兜底队列。
- 新增交付状态 `not_configured/queued/sending/sent/partial/needs_attention/shadowed/manual`；
  **`sent` 定义为"已成功投递下游"**，审批状态机不变。
- 新规则默认 `shadow`（只组包记录、不发送），由 Bank Ops 显式升级为 `needs_review` → `auto_send`；
  提供全局 kill switch，关闭后所有 `auto_send` 降级为 `shadow`。
- 新增 Runs 面板（查看 / 重试 / 取消 / needs_review 放行）与文档交付徽标；
  `Review & send` 的手动 `Preview request` / `Send` 保留为人工通道。
- API Keys 的 `automation.use/apply` scope 保留一版 deprecated，避免既有集成立即失效。

## Capabilities

### New Capabilities

- `automation-access-control`: Automation 模块的可见性、配置/发送权限、部门作用域、审计与现有手动通道的访问边界。
- `automation-auto-dispatch`: 模板绑定、规则模型、终审触发、多下游 fan-out、幂等/重试、交付状态、运行面板与 shadow 档位。

### Modified Capabilities

<!-- 无：审批状态机（draft → pending_first → pending_second → approved）不变；
     交付状态属于 automation 能力，不修改现有 spec 的 requirement。 -->

## Impact

- 权限与身份：`app/identity/permissions.py`（权限目录 + 角色矩阵）、`app/identity/principal.py`
  （capability 映射）、`app/shared/ports.py`（Principal 字段复用）。
- 后端：`app/api/automation.py`（路由级 dependency + 新路由）、`app/automation/registry.py`
  （按 view/configure/dispatch 判权）、新增 `app/automation/rules.py` / `app/automation/jobs.py` /
  `app/automation/worker.py`、`app/documents/store.py`（schema 迁移、outbox 消费标记）。
- 数据：新增 `automation_rules`、`automation_jobs`、`automation_job_events`；
  `automation_dispatches` 增列 `job_id/rule_id/trigger/submission_id`；`documents` 增列模板绑定；
  `outbox_events.delivered_at` 作为消费位点。`SCHEMA_VERSION` 递增并保持向后兼容迁移。
- 前端：`web/src/components/AssistantPanel.tsx`（tab gating）、`App.tsx`（`openModule` 深链守卫）、
  `AutomationWorkbench` / `AutomationServerPanel`（Rules / Runs、文档交付徽标）、`web/src/api/automationRegistry.ts`。
- 部署：新增单实例 `automation-worker` systemd unit（SQLite 单写者约束，见 `deploy/README.md`）。
- 演示/文档：`DEMO.md`、`DEMO_automation.md`、`README.md` 需改用 Bank Ops 账号并补充自动投递流程。
- 依赖：建立在 in-flight 的 `automation-template-registry`（模板 / 连接器 / 映射 / 回执）之上，
  该能力未归档前本 change 不应单独发布。