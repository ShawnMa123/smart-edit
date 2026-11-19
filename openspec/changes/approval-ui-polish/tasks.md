# Tasks

## 1. 状态模型与过期文案（P0）

- [x] 1.1 新增 `web/src/domain/approvalStatus.ts` 与 `StatusBadge`，覆盖 6 个状态、tone、图标、readOnly、nextActor、aria label；验证：单测覆盖全部状态与未知状态
- [x] 1.2 `DocumentHead` 接收真实 submission 状态，替换硬编码 `Draft`；显示当前审批角色、revision、最近意见；验证：组件测试覆盖 Draft/Pending/Approved/Returned
- [x] 1.3 `EnvironmentStrip` 增加 authenticated 文案；`DocumentActions` 移除 `Start approval` not-available；验证：真实模式不再出现 “does not approve or submit”，fake/demo 测试仍通过

## 2. 即时反馈（P1）

- [x] 2.1 新增轻量 `ToastProvider`/`useToast`：success/info/warning/error、最多 3 条、aria-live、action；验证：组件测试覆盖四种变体、自动/手动关闭、action
- [x] 2.2 提交成功、审批决策、邀请复制接入 Toast；失败保留表单并显示 error；验证：提交/决策/People 组件测试覆盖成功与失败路径

## 3. 等待审批与 My Submissions（P1）

- [x] 3.1 新增 `ApprovalStatusBanner` + 四步 stepper：当前阶段、等待角色、提交时间、revision、最近意见、只读说明；验证：组件测试覆盖 pending_first/pending_second/approved/returned
- [x] 3.2 `ApprovalPanel` 的 My submissions 改为卡片列表（状态/revision/时间/阶段/意见），选中显示时间线；验证：组件测试覆盖多条提交与空态
- [x] 3.3 Applicant pending 状态 10s 轮询，页面隐藏暂停，approved/returned/rejected 停止；验证：fake timer 测试覆盖轮询、停止与不可见页面

## 4. 顶部入口与真实计数（P1）

- [x] 4.1 `TOPBAR_ENTRIES` 增加 Approval；`TopBar` 支持 `approvalCount` / `activityUnread`，0 隐藏、>99 显示 99+；验证：AppShell 组件测试覆盖 badge
- [x] 4.2 App 在 authenticated 模式聚合 `/approvals` 待办数与 `/activity/unread-count`；fake/demo 保留本地计数；验证：组件测试覆盖服务端计数与鉴权失败回退

## 5. 文档与回归

- [x] 5.1 更新 `how_to_use.md` / `README.md`：Pending Banner、状态含义、顶部 badge、Toast、轮询；验证：按文档在 PG 模式走一次提交并看到等待界面
- [x] 5.2 回归：`npm --prefix web run typecheck`、`npm --prefix web run test`、`.venv/bin/python -m pytest tests -q`、`openspec validate approval-ui-polish --strict`；验证：四条命令通过

## Workflow follow-up

- 评审通过后归档本 change。
- P2/P3（审批工作台重做、Activity/Inbox 合并、移动端、SLA）留到后续 change。