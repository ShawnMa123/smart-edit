# Design

## Context

动机见 `proposal.md` — Why；行为契约见 `specs/document-submission` 与 `specs/document-approval`。塑造实现方式的现有事实：

- 文档在 **SQLite** `runs/host.db`：`documents`、`document_drafts`、`document_checkpoints`、`document_locks`；锁带 `fencing_token` 与租约，`DocumentService` 已按 `document.read/edit/lock` 做 PG 授权。
- 身份与角色在 **PostgreSQL**：`user-management` 已有 `Principal`、`AuthorizationService`、Activity 与 `applicant / bank_ops / compliance` 角色；但审批权限尚未定义。
- 现有 `Submit new version` 只是占位对话框；Approval 模块是 `UnavailableModuleDialog`；Automation apply 会产生新 revision，并写一条 “document version submitted” Activity，但那不是审批提交。
- 文档读模型以 `workspace_id + department_id` 判定范围；审批可见性必须复用组织/部门授权，而不是新增一套 ACL。

## Goals / Non-Goals

**Goals:**

- 提交时冻结不可变快照，审批人永远看同一份内容。
- 串行两级审批：`pending_first → pending_second → approved`，支持 `returned / rejected`。
- 提交期间禁止编辑；退回后允许 Applicant 修改并产生新提交。
- 权限、自审限制、并发决策和 Activity/审计都可测试。

**Non-Goals:**

- 不做邮件、推送、实时协作、并行会签、委托、超时升级。
- 不把审批快照写入 PostgreSQL；身份/权限在 PG，文档与审批数据仍留在 host SQLite。
- 不在本轮把 AI audit gate 绑定到提交/审批；`start_approval` gate 的接入留待后续。
- 不提供审批意见富文本、附件或电子签名。

## Decisions

### D1 · 审批数据放在 host SQLite，与文档同一事务边界

新增三张表（`SCHEMA_VERSION` 3 → 4）：

```text
document_submissions(
  submission_id PK, document_id, draft_id, workspace_id, department_id,
  submitted_by, revision, content_sha256, content_json, text,
  variables_json, variables_version, status, created_at)
approval_requests(
  request_id PK, submission_id UNIQUE, document_id, workspace_id, department_id,
  submitted_by, status, current_stage, revision, created_at, updated_at, decided_at)
approval_steps(
  step_id PK, request_id, stage, decision, actor_user_id, comment,
  expected_revision, created_at, decided_at,
  UNIQUE(request_id, stage))
```

理由：提交必须与草稿 revision、锁释放原子提交；把审批元数据放到 PG 会引入跨库事务与不一致。备选“全部放 PG”否决：现有文档 host 不在 PG，且迁移文档数据不是本 change 的范围。

### D2 · 提交快照复制正文，而不是引用 draft

提交时在同一 SQLite 事务内读取当前 draft，复制 `content_json/text/variables/version` 与 `text_sha256` 到 `document_submissions`，写入请求，释放锁。审批详情只读快照，不再 join 当前 draft。

理由：审批必须绑定提交时的内容；引用 draft 会在退回后修改时污染历史。备选“只存 revision、详情再读 draft”否决。

### D3 · 锁与提交的原子校验

`POST /documents/{id}/submissions` 要求 `lock_id + fencing_token + expected_revision`：

1. `validate_lock`（所有者、未释放、未过期、fencing token 匹配）；
2. 当前 draft `revision == expected_revision` 且 `text_sha256` 与请求一致；
3. 复制快照、创建 request、`status=pending_first`、释放锁；
4. 任一步失败整体回滚。

### D4 · 提交期间禁止编辑

`DocumentService.acquire_lock` 与 `save_draft` 在获取/保存前检查该文档最新 submission 状态：

- `pending_first` / `pending_second` / `approved` → `409 submission_pending`；
- `returned` / `rejected` / 无提交 → 允许编辑。

理由：服务端必须兜底，不能只靠 UI 禁用按钮。备选“允许继续编辑但不允许再提交”否决：审批人看到的快照与申请人当前草稿会分叉。

### D5 · 审批状态机与并发

请求 `revision` 每次决策递增；决策请求必须带 `expected_revision`。状态迁移：

```text
pending_first --first approve--> pending_second --second approve--> approved
pending_first --return/reject--> returned/rejected
pending_second --return/reject--> returned/rejected
```

First/Second 权限分离；`actor_user_id == submitted_by` 直接 403；已终态请求再决策 409。备选“用 updated_at 做并发控制”否决：时间戳不稳定，整数 revision 更容易测试。

### D6 · 权限目录扩展

在 `app/identity/permissions.py` 增加：

- `approval.submit` → `applicant`
- `approval.first` → `bank_ops`
- `approval.second` → `compliance`
- `org_admin` 获得三者用于管理与排障，但仍受“不能审批自己提交的请求”约束。

### D7 · API 形态

```text
POST /documents/{document_id}/submissions         Applicant 提交
GET  /documents/{document_id}/submissions         Applicant 查看历史/当前状态
GET  /approvals?status=pending&stage=first|second 审批待办
GET  /approvals/{request_id}                      快照 + 时间线
POST /approvals/{request_id}/decisions            approve/return/reject + comment
```

沿用现有 `If-Match`/`expected_revision` 风格；决策使用 JSON body 的 `expected_revision`，避免与文档 ETag 混淆。

### D8 · 活动与审计

复用 `ActivityService.safe_record`：`submission.created`、`approval.first.approved`、`approval.second.approved`、`approval.returned`、`approval.rejected`。载荷只含 request/submission ID、stage、decision、actor；正文绝不入 Activity。审批详情本身可读快照，但 Activity 不复制正文。

### D9 · 前端状态与只读

- `Submit new version` 改为真实对话框：提交前展示 revision、内容摘要、目标审批链；提交成功后显示状态条并刷新锁状态。
- 文档头显示 `Draft / Pending first / Pending second / Approved / Returned / Rejected`；`pending_*` 与 `approved` 时编辑器只读，`returned` 显示退回意见并允许重新获取锁。
- Approval 模块替换占位：待办列表按 `approval.first|second` 过滤；详情左侧只读快照、右侧决策与 comment；Applicant 打开时显示自己的提交时间线。
- 复用现有 `lockNotice` / `WorkspaceDialog` 风格，不新建第二套状态机。

### D10 · 兼容 `AUTH_MODE=fake`

`AUTH_MODE=fake` 下没有真实身份与审批权限：提交/审批 API 返回 `AUTH_MODE_FAKE` 或明确不可用；现有 demo（`?demo=1`）继续走本地演示，不伪造提交成功。

## Risks / Trade-offs

- [提交与锁的并发窗口] → 快照、request、锁释放放在同一个 `BEGIN IMMEDIATE` 事务；`validate_lock` 在事务内再次执行。
- [快照体积增长] → 只复制正文/变量/摘要，不复制附件；后续可加保留策略（本 change 不做）。
- [退回后旧审批记录污染新版本] → 每次重新提交创建新 submission/request；旧记录只读。
- [同一用户同时持两级权限] → 自审禁止；但同一非提交者仍可能连续两级审批。若需要强制不同人，可在后续增加 `first_actor != second_actor` 配置，本 change 不默认启用。
- [审批人看不到文档正文] → 详情 API 返回快照；前端不依赖 editor 锁来阅读。
- [没有邮件导致审批人漏看] → Activity + 待办列表 + 页面状态；邮件在后续 change。
- [AI audit gate 未接入] → 提交只校验锁与 revision；规则门禁接入是后续工作，文档中明确标注。

## Migration Plan

1. SQLite `SCHEMA_VERSION=4`：新增三张表，旧库自动迁移；旧文档无提交记录，行为不变。
2. 权限目录增加三个 permission 并同步到 PG；`applicant / bank_ops / compliance` 重新同步角色权限。
3. 后端先上提交/审批 API，再切前端 `Submit new version` 与 Approval 模块；`AUTH_MODE=fake` 保持原占位。
4. 回滚：保留新表不删；前端可回退到占位按钮；审批数据不影响草稿读写。

## Open Questions

- 审批是否需要与现有 AI audit gate（`start_approval`）绑定？本 change 先不绑定。
- 是否要求 First/Second 必须由不同用户完成？当前只禁止自审，保留配置位。
- 审批保留期限与归档策略？沿用 Activity 的 180 天待定策略。