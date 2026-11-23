# Proposal

## Why

两级审批已经能真实提交和处理，但 UI 仍像工程控制台：文档头永远显示 `Draft`；提交后只有页脚一行状态；审批待办没有数量/等待界面；顶部没有 Approval 入口；所有提示都是同一种黄色 notice；环境条和动作按钮还在说“审批不可用”。这些不一致会让申请人不知道“现在轮到谁”，也让审批人找不到待办。

本轮只做 **P0 一致性修复 + P1 提交/等待体验**，不重做审批工作台、不统一 Activity/Inbox。

## What Changes

- 新增共享审批状态模型与 `StatusBadge`：`Draft / Pending first / Pending second / Approved / Returned / Rejected` 使用统一的文案、图标、色调、只读语义与无障碍标签。
- 文档头使用真实状态替代硬编码 `Draft`；页脚、Approval 列表、Activity 使用同一套状态显示。
- 新增 **Pending Approval Banner + Stepper**：提交后在文档上方显示“Waiting for Bank Operations / Compliance”、时间线、提交时间、最近意见与只读说明。
- Approval → **My submissions** 改为卡片列表：显示状态、revision、提交时间、当前阶段、最近意见；选中后显示详情与时间线。
- 顶部导航增加 **Approval** 入口与待办数 badge；Activity badge 改用服务端未读数；不把本地浏览器通知伪装成服务器待办。
- 新增轻量 **Toast**：提交成功、审批结果、复制邀请等即时反馈使用成功/信息/警告/错误四种语义；持久状态（只读、退回意见、冲突）仍用内联 banner。
- 移除过期文案与假占位：环境条不再说“does not approve or submit”；`DocumentActions` 不再把 Start approval 标为 not available。
- Applicant 在 pending 状态自动刷新（页面可见时轮询，终态停止）；不再要求手动刷新才能看到审批进度。
- 明确不做：审批工作台左右分栏重做、Activity/Inbox 合并、SLA/超时、意见模板、移动端详情重构（留到后续 P2/P3）。

## Capabilities

### New Capabilities

- `approval-status-ui`: 文档/审批的状态模型与 badge、Pending Approval Banner/Stepper、My submissions 卡片、顶部 Approval 待办入口与计数、提交成功 Toast、过期文案清理与状态自动刷新。

### Modified Capabilities

- `document-editor`: 文档头显示真实审批状态；`Start approval` 不再标记为不可用；只读/退回状态与提交反馈保持一致。

## Impact

- **前端组件**：`AppShell`（DocumentHead/EnvironmentStrip/TopBar）、`RichEditor`（状态/只读文案）、`ApprovalPanel`（My submissions 卡片）、`DocumentActions`（移除假审批动作）、`App`（状态、轮询、toast、顶部计数）。
- **新增前端模块**：`web/src/domain/approvalStatus.ts`、`StatusBadge`、`ApprovalStatusBanner`、轻量 `ToastProvider`。
- **API**：复用现有 `/approvals`、`/documents/{id}`、`/documents/{id}/submissions`、`/activity/unread-count`；不需要数据库或后端权限变更。
- **样式**：新增状态 tone、stepper、banner、toast、badge 的样式；保持现有 chip/tag 体系兼容。
- **测试**：状态映射/badge、文档头动态状态、Pending Banner、My submissions、顶部 badge、Toast、轮询停止、过期文案回归。
- **兼容性**：`AUTH_MODE=fake` / `?demo=1` 保留原演示路径，不显示真实审批状态。