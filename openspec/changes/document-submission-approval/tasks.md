# Tasks

## 1. 数据模型与迁移

- [x] 1.1 SQLite `SCHEMA_VERSION` 3→4，新增 `document_submissions`、`approval_requests`、`approval_steps` 与索引；旧库自动迁移且旧文档读取不变。验证：`tests/test_document_host_store.py` 覆盖 v3→v4 迁移、重复执行幂等、旧数据可读
- [x] 1.2 新增提交/审批存储层（创建提交快照、查询当前提交、按状态/权限查询审批、决策事务）；验证：单元测试覆盖快照复制后草稿变化不影响历史、终态不可变

## 2. 提交后端

- [x] 2.1 `POST /documents/{id}/submissions`：校验锁 + fencing token + `expected_revision` + 内容摘要，原子创建快照/请求并释放锁。验证：API 测试覆盖成功、stale revision 409、缺失/他人锁 403/409
- [x] 2.2 `GET /documents/{id}/submissions`：提交者查看历史与最新状态，返回不含正文的摘要。验证：API 测试覆盖 Applicant 只见本人提交、跨部门 403
- [x] 2.3 `DocumentService` 增加提交期编辑保护：`pending_first/pending_second/approved` 时拒绝 `acquire_lock` 与 `save_draft`，`returned/rejected` 或无提交允许。验证：API 测试覆盖 pending 409、returned 后可编辑、approved 仍只读
- [x] 2.4 提交/退回/通过/驳回写 Activity 事件（`submission.created` 等，载荷不含正文/令牌）。验证：单测断言事件字段与敏感内容缺失
- [x] 2.5 在 `how_to_use.md` 的文档编辑章节补充提交与只读规则。验证：按文档步骤在 PG 模式完成一次提交

## 3. 审批后端

- [x] 3.1 权限目录增加 `approval.submit / approval.first / approval.second` 并绑定 Applicant / Bank Ops / Compliance（org_admin 管理用）；同步角色目录。验证：权限矩阵单测 + `tests/test_identity_schema.py` 角色同步断言
- [x] 3.2 审批领域服务：两级状态机、`expected_revision` 乐观并发、禁止自审、退回/驳回必须带意见、终态不可重放。验证：单测覆盖 first approve、second approve、return、reject、并发 409、自审 403
- [x] 3.3 API：`GET /approvals`（按 first/second 与组织范围过滤）、`GET /approvals/{id}`（冻结快照 + 时间线）、`POST /approvals/{id}/decisions`。验证：API 测试覆盖角色越权 403、阶段错误 409、退回无意见 422、申请人/审批人可见性
- [x] 3.4 审批事件与审计：`approval.first.approved`、`approval.second.approved`、`approval.returned`、`approval.rejected`；不发送邮件。验证：Activity API 测试可见且载荷不含正文
- [x] 3.5 在 `README.md`/`how_to_use.md` 记录审批 API、角色权限与“无邮件”的 v1 边界。验证：文档命令与实际 API 响应一致

## 4. 前端提交与状态

- [x] 4.1 `web/src/api` 增加 submissions/approvals client 与类型；写操作带 `credentials` + CSRF 头。验证：client 单测覆盖 URL/method/header 与错误映射
- [x] 4.2 `Submit new version` 改为真实提交对话框：显示 revision/摘要/审批链，成功后刷新状态并释放锁。验证：组件测试覆盖成功、409 stale、无权限不可提交
- [x] 4.3 文档头/页脚显示 `Draft / Pending first / Pending second / Approved / Returned / Rejected`；`pending_*` 与 `approved` 只读，`returned` 显示意见并允许重新加锁。验证：组件测试覆盖只读与退回后可编辑

## 5. 前端审批收件箱

- [x] 5.1 将 Approval 模块从 `UnavailableModuleDialog` 替换为真实待办列表（first/second 过滤）与详情（只读快照 + 时间线）。验证：组件测试覆盖待办渲染、空态、403 无权态
- [x] 5.2 决策界面：Approve / Return / Reject + 必填意见（return/reject），提交后刷新状态；申请人在同一模块看自己的提交时间线。验证：组件测试覆盖三种决策、无意见校验、状态刷新
- [x] 5.3 更新 `how_to_use.md` 的审批操作步骤与截图级说明。验证：按文档用 Applicant → BankOps → Compliance 完成一次两级审批

## 6. 集成与验收

- [x] 6.1 端到端脚本/测试：Applicant 提交 → BankOps 一审通过 → Compliance 二审通过 → 文档只读；以及退回 → 修改 → 重新提交。验证：PG 模式验收测试通过
- [x] 6.2 验收记录写入 change 目录（请求、状态变化、Activity 事件、审批意见）。验证：`openspec/changes/document-submission-approval/acceptance.md` 完整可复现
- [x] 6.3 回归：`.venv/bin/python -m pytest tests -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate document-submission-approval --strict`。验证：四条命令通过

## Workflow follow-up

- 评审通过后归档本 change；归档前用 seed 账号完整跑一次两级审批。
- 后续 change 再接 AI audit `start_approval` gate、邮件通知、并行会签与超时升级。