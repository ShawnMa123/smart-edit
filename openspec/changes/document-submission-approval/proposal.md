# Proposal

## Why

Applicant 已经可以在服务端草稿上编辑并自动保存，但“提交版本”仍是占位按钮：没有不可变提交快照、没有审批请求、没有 First/Second Approver 的待办与决策，因此 Bank Operations 与 Compliance 只能以只读方式看最新草稿，无法形成可审计的两级审批闭环。

## What Changes

- 新增**不可变提交版本**：Applicant 提交时冻结当前草稿的 revision、正文、变量与内容摘要；提交后正文不再随草稿变化。
- 新增**两级审批请求**：First Approver（Bank Operations）通过后进入 Second Approver（Compliance）；支持 `approve / return / reject`，退回后 Applicant 修改并重新提交新版本。
- 新增**审批权限**：`approval.submit`、`approval.first`、`approval.second`，分别绑定 Applicant、Bank Operations、Compliance 角色；禁止审批自己提交的请求。
- 新增**提交与审批 API**：提交、待办列表、详情（含快照与时间线）、决策；所有写操作带乐观版本与锁校验。
- 新增**状态机**：`pending_first → pending_second → approved`，以及 `returned / rejected` 终态；状态变化写 Activity 与审计事件。
- 前端：把 `Submit new version` 占位替换为真实提交对话框与状态条；把 Approval 的 “not available” 模块替换为待办/详情/决策界面；审批中的版本只读。
- **BREAKING**：已提交且未结束审批的文档不能再获取编辑锁；`Submit new version` 不再只是本地捕获。
- **明确不做（本轮）**：邮件通知、并行会签、委托/超时升级、审批意见富文本、审批附件、审批快照的 AI 自动审查门禁、跨组织审批。

## Capabilities

### New Capabilities

- `document-submission`: 不可变提交版本、提交/重新提交、提交状态、提交期间的编辑锁约束。
- `document-approval`: 两级审批请求、待办与详情、通过/退回/驳回、禁止自审、审批权限与审计/活动事件。

### Modified Capabilities

- `document-editor`: `Submit new version` 从占位变为真实提交；文档头/页脚显示提交与审批状态；审批进行中只读。

## Impact

- **数据库**：SQLite `runs/host.db` 新增 `document_submissions`、`approval_requests`、`approval_steps`；`SCHEMA_VERSION` 升级并保持旧数据可读。
- **后端**：`app/documents` 增加提交领域；新增 `app/approval`（或 `app/documents/submission.py`）与 `/documents/{id}/submissions`、`/approvals*` API；`DocumentService` 在提交/退回/批准后约束锁与保存；`AuthorizationService` 增加审批动作；Activity 写入审批事件。
- **权限**：`app/identity/permissions.py` 增加 `approval.submit` / `approval.first` / `approval.second`；Applicant、Bank Operations、Compliance 角色获得对应权限；org_admin 可用于管理但同样禁止自审。
- **前端**：`App.tsx`、`RichEditor` footer、`DocumentActions`、`Approval` 模块、`People` 角色展示；新增提交/审批 API client 与测试。
- **兼容性**：现有 `AUTH_MODE=fake` 与 `?demo=1` 路径保持可用；真实提交只在 PG 身份模式下启用。
- **测试/文档**：提交快照不可变、审批状态机、越权/自审/并发、只读约束、Activity；更新 README/how_to_use 与验收记录。