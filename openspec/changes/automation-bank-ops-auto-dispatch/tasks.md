# Tasks

## 1. 权限收口（P0）

- [x] 1.1 在 `app/identity/permissions.py` 新增 `automation.view/configure/dispatch/audit` 并更新
  `applicant/member/dept_admin/bank_ops/compliance/org_admin` 矩阵；用角色权限快照测试验证每个角色的
  权限集合（`pytest tests/test_identity_permissions*`）。
- [x] 1.2 在 `app/identity/principal.py` 增加 capability 映射，并给 `/automation` 路由加统一鉴权
  dependency（view/configure/dispatch/audit）；新增 403 矩阵测试覆盖四类角色与每个写接口。
- [x] 1.3 旧 API Key scope 降级映射（`automation.use→view`、`automation.apply→dispatch`，均不授予
  configure）；测试断言旧 Key 可发送但配置接口返回 403。
- [x] 1.4 前端 `AssistantPanel` 按 `permissions` 过滤 Automation tab、`App.openModule` 拦截深链并显示
  无权限说明、fake/demo 模式保持可用；vitest 覆盖 bank_ops / dept_admin / compliance / applicant 四种视图。
- [x] 1.5 更新 `README.md` 与 `DEMO*.md` 的角色入口说明与演示账号切换，并按文档步骤实际走一遍确认可执行。

## 2. 模板绑定（P1）

- [x] 2.1 为 `documents` 增加 `template_id` / `template_name`（或等价绑定表）并递增 `SCHEMA_VERSION`；
  迁移测试覆盖"老库打开后新列存在、旧数据不报错"。
- [x] 2.2 模板套用创建文档时写入绑定并记审计；pytest 断言 apply 后文档带精确 `template_id` 与
  `template_name`。
- [x] 2.3 新增文档绑定/改绑 API 与 Setup 面板入口；pytest 覆盖成功、越权、跨部门拒绝，vitest 覆盖入口渲染。
- [x] 2.4 自动链路跳过未绑定文档并给出 `no_binding` 原因；pytest 覆盖终审通过但未绑定时不创建 job。

## 3. 规则与 shadow（P2）

- [x] 3.1 新增 `automation_rules` 表（含 `department_id`、`template_name`、`connector_id`、`trigger`、
  `mode`、`required`、`priority`）与 CRUD API；pytest 覆盖 `dept_admin` 仅本部门、`bank_ops` 组织级、
  跨部门改删被拒。
- [x] 3.2 规则保存校验：模板名与连接器必须存在、同一模板重复指向同一 connector 产生告警；pytest 覆盖
  校验错误与告警字段返回。
- [x] 3.3 `POST /automation/rules/{id}/dry-run` 复用 `preview()` 输出请求体与 issues，且不写
  `automation_dispatches`；pytest 断言回执行数不变。
- [x] 3.4 前端新增 Rules 页签（列表、新建/编辑、启停、档位与命中告警）；vitest 覆盖列表渲染、保存与停用。
- [x] 3.5 把规则配置与 shadow 观察步骤补进 `DEMO_automation.md`，并按文档步骤验证可复现。

## 4. Worker 与多下游投递（P3）

- [x] 4.1 新增 `automation_jobs` / `automation_job_events` 表、`(workspace_id, idempotency_key)` 唯一约束与
  `(status, next_attempt_at)` 索引；迁移测试覆盖唯一约束冲突被拒绝。
- [x] 4.2 新增按 submission 快照组包的内部路径（`prepare_from_text` 或预组 `values`）；pytest 断言审批后
  继续编辑草稿不改变自动任务的 payload。
- [x] 4.3 实现 worker：消费未投递的 `approval.second.approve`、标记 `delivered_at`、补偿扫描到期任务；
  pytest 用 echo 下游验证一次终审只产生预期 job。
- [x] 4.4 实现 fan-out（每个命中规则一条 job）、同 connector 去重、required/optional 聚合 delivery；
  pytest 覆盖"3 下游 2 成功 1 失败 → needs_attention"与"optional 失败仍 sent"。
- [x] 4.5 实现幂等与重试分类（5xx/timeout 退避最多 3 次；4xx/refused/missing_required_body 不重试）；
  pytest 覆盖重复调度只发一次、500 重试成功、409 直接 needs_attention。
- [x] 4.6 回执关联 `job_id/rule_id/submission_id/template_id` 并使用系统操作者身份；pytest 断言回执字段与
  `requested_by`。
- [x] 4.7 新增 `automation-worker` systemd unit 与 `SMART_EDIT_AUTOMATION_WORKER` / kill switch 环境变量，
  更新 `deploy/README.md`；按文档命令启动 worker 并确认能处理一条 shadow 任务。
- [x] 4.8 在 `README.md` / `DEMO_automation.md` 记录自动投递开关、档位与回滚步骤，并按步骤验证关闭后不再外发。

## 5. 运行面板与档位升级（P4）

- [x] 5.1 实现 Runs API（列表、详情、retry、cancel、needs_review 放行）；pytest 覆盖状态机合法/非法迁移。
- [x] 5.2 实现文档交付聚合 API（含每个下游一行与跳过原因）；pytest 覆盖 sent / partial / needs_attention /
  not_configured。
- [x] 5.3 前端新增 Runs 页签与文档交付徽标；vitest 覆盖列表、详情时间线、放行与重试按钮的可用性。
- [x] 5.4 实现档位升级/降级 API 与审计，并在面板显示 kill switch 状态；pytest + vitest 覆盖升级留痕与
  关闭开关后的 shadow 降级。
- [x] 5.5 交付状态变化写入 Activity 事件（`kind: automation`）；pytest 断言事件内容含文档、下游与状态。
- [x] 5.6 更新 `README.md` / `DEMO.md` 的运行面板说明，并补一条 e2e：终审通过 → 自动 sent。

## 6. 集成验证

- [x] 6.1 端到端演练：Bank Ops 建规则（shadow）→ 终审 → 只产生 shadow 记录 → 升 `auto_send` → 终审 →
  多下游收到请求且文档状态 `sent`；用 echo 下游跑通 e2e。
- [x] 6.2 权限回归：四种角色 + 旧 API Key 的 UI 与 API 矩阵全部符合 `specs/automation-access-control`；
  pytest + vitest 全绿。
- [x] 6.3 回滚演练：关闭 kill switch 与 worker 后不再产生外发，隐藏/恢复 Automation 入口符合权限矩阵；
  按 `Migration Plan` 步骤验证。

## Workflow follow-up

- 评审通过后归档本 change，并确认 `automation-template-registry` 仍处于可依赖状态。
- 归档后检查 `openspec/specs/automation-access-control` 与 `automation-auto-dispatch` 的 Purpose 与
  requirement 文案是否与最终实现一致。