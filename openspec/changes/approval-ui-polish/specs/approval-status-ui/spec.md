# Spec Delta

## Purpose

定义文档审批状态在界面上的统一呈现、等待审批主界面、申请人提交历史卡片、顶部待办计数与即时反馈，让用户无需猜测“现在轮到谁”或手动刷新。

## ADDED Requirements

### Requirement: Approval status MUST use one shared model

文档头、页脚、Approval 列表、Activity 与顶部 badge SHALL 使用同一套状态映射（`draft / pending_first / pending_second / approved / returned / rejected`）；状态 MUST 同时包含可读文本与非颜色提示，MUST NOT 在已提交文档上显示 `Draft`。

#### Scenario: Submitted document header

- **WHEN** 文档最新提交状态为 `pending_first`
- **THEN** 文档头显示 `Pending first approval`（或等价的 “Waiting for Bank Operations”）
- **AND** MUST NOT 显示 `Draft`

#### Scenario: Status is not colour-only

- **WHEN** 任一状态 badge 被渲染
- **THEN** 它包含文本与图标/形状提示
- **AND** 其可访问名称包含完整状态

### Requirement: Pending approval MUST show a waiting banner and stepper

申请人存在进行中提交时，文档区域 SHALL 显示等待审批 banner，包含当前阶段、下一审批角色、四步进度（Submitted / Bank Operations / Compliance / Approved）、提交时间、revision 与最近审批意见；banner MUST 明确说明只读原因。

#### Scenario: Waiting for first approver

- **WHEN** 状态为 `pending_first`
- **THEN** banner 高亮 Bank Operations 阶段并显示 “Waiting for Bank Operations”
- **AND** 显示“编辑已锁定，退回或批准后恢复/结束”

#### Scenario: Waiting for second approver

- **WHEN** First Approver 通过后状态为 `pending_second`
- **THEN** banner 高亮 Compliance 阶段并显示 “Waiting for Compliance”
- **AND** 页面无需手动刷新即可在轮询周期内更新

### Requirement: Applicant MUST see submission cards and timeline

Approval 的 **My submissions** SHALL 以卡片列出每次提交的状态、revision、提交时间、当前阶段与最近意见；选中卡片 SHALL 显示该提交的冻结快照摘要与时间线，历史提交 MUST NOT 被新提交覆盖。

#### Scenario: Multiple submissions

- **WHEN** 文档先被退回后重新提交
- **THEN** My submissions 同时显示 returned 与 pending_first 两条记录
- **AND** 两条记录可分别查看意见与时间线

#### Scenario: Terminal status stops polling

- **WHEN** 最新状态为 approved、rejected 或 returned
- **THEN** 页面停止自动轮询该文档状态

### Requirement: Top bar MUST expose approval work and server counts

顶部导航 SHALL 提供 Approval 入口；持有人审批权限时 SHALL 显示当前组织的待办数量 badge；Activity badge SHALL 使用服务端未读数，MUST NOT 使用浏览器本地通知数量冒充服务器待办。

#### Scenario: First approver badge

- **WHEN** Bank Operations 有 2 条 `pending_first`
- **THEN** 顶部 Approval badge 显示 2
- **AND** 0 条时 badge 隐藏而不是显示 0

#### Scenario: Activity unread count

- **WHEN** 服务端 Activity 有 3 条未读
- **THEN** 顶部 Activity badge 显示 3
- **AND** 标记已读后计数更新

### Requirement: Immediate feedback MUST use semantic toasts

提交成功、审批通过/退回/驳回、复制邀请等即时结果 SHALL 通过语义化 Toast 呈现（success / info / warning / error），并 MUST 使用 live region 供辅助技术播报；持久状态（只读、退回意见、冲突）MUST 保留内联 banner。

#### Scenario: Submit success

- **WHEN** 申请人提交成功
- **THEN** 出现 success Toast，包含 “Submitted for approval” 与 “View approval” 动作
- **AND** 不只依赖页脚一行提示

#### Scenario: Failed write

- **WHEN** 提交或决策返回 4xx
- **THEN** 出现 error Toast 并保留当前表单/详情状态
- **AND** MUST NOT 显示成功文案

### Requirement: Authenticated copy MUST not claim approval is unavailable

真实 PG 模式下，环境条、文档动作与 Approval 页面 MUST NOT 声称“审批未实现 / 不提交 / 演示数据”；只有 `AUTH_MODE=fake` 或 `?demo=1` MAY 显示演示说明。

#### Scenario: Authenticated shell copy

- **WHEN** 用户已登录且页面不是 demo 模式
- **THEN** 环境条说明服务端身份、草稿与审批已启用
- **AND** `Start approval` 不再标记为 `Not available`

#### Scenario: Fake mode unchanged

- **WHEN** `AUTH_MODE=fake` 或 `?demo=1`
- **THEN** 仍显示原有演示说明与演示审批
- **AND** 不伪造真实提交成功