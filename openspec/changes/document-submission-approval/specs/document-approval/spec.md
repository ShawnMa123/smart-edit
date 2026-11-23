# Spec Delta

## Purpose

定义文档的两级审批：First Approver 与 Second Approver 的权限、待办与详情、通过/退回/驳回状态机、自审限制，以及每次决策的审计与活动记录。

## ADDED Requirements

### Requirement: Approval stages MUST require their own permission

审批请求 SHALL 依次经过 First Approver 与 Second Approver；只有持有 `approval.first` 的用户可以处理第一阶段，只有持有 `approval.second` 的用户可以处理第二阶段。

#### Scenario: First approver sees the first-stage inbox

- **WHEN** Bank Operations 用户请求待办
- **THEN** 只返回 `pending_first` 且属于其组织范围的请求

#### Scenario: Member cannot approve

- **WHEN** 只有 `member` 角色的用户尝试通过审批
- **THEN** 请求返回 403，且不改变状态

#### Scenario: Second stage cannot start early

- **WHEN** 请求仍为 `pending_first` 时 Second Approver 尝试决策
- **THEN** 请求返回 409，并提示当前阶段不是第二审批

### Requirement: Approval state machine MUST be explicit

审批状态 SHALL 为 `pending_first`、`pending_second`、`approved`、`returned`、`rejected`；合法迁移 MUST 只有 First 通过进入第二、Second 通过进入批准，以及任一阶段退回或驳回进入终态。

#### Scenario: First approval advances the stage

- **WHEN** First Approver 通过 `pending_first` 请求
- **THEN** 状态变为 `pending_second`
- **AND** Applicant 的状态查询立即反映该变化

#### Scenario: Second approval completes the flow

- **WHEN** Second Approver 通过 `pending_second` 请求
- **THEN** 状态变为 `approved`
- **AND** 该提交不可再被审批或编辑

#### Scenario: Terminal decisions cannot be replayed

- **WHEN** 对已 `approved`、`returned` 或 `rejected` 的请求再次提交决策
- **THEN** 请求返回 409，且原状态不变

### Requirement: Submitters MUST NOT approve their own submission

审批人 MUST NOT 对本人提交的请求做任何决策；系统 MUST 以服务端主体判定，而不是客户端字段。

#### Scenario: Self approval is rejected

- **WHEN** 提交者同时持有 `approval.first` 并尝试通过自己的提交
- **THEN** 请求返回 403，且请求状态保持 `pending_first`

### Requirement: Decisions MUST bind to the step and expected revision

每次决策 MUST 校验请求当前 revision、当前阶段与提交快照；过期或并发决策 MUST 返回 409，不得覆盖他人决策。

#### Scenario: Concurrent decisions

- **WHEN** 两个 First Approver 同时提交决策，只有一个携带当前 revision
- **THEN** 一个决策成功，另一个返回 409
- **AND** 审批记录只包含一次有效决策

#### Scenario: Decision snapshot is immutable

- **WHEN** 审批人查看详情
- **THEN** 返回冻结的提交正文、revision 与内容摘要
- **AND** 不返回后来修改的草稿

### Requirement: Return and reject MUST carry a reason

`return` 与 `reject` MUST 要求非空意见；`approve` MAY 带意见。每次决策 MUST 保存审批人、阶段、时间与意见。

#### Scenario: Return without comment is rejected

- **WHEN** 审批人提交 `return` 但没有意见
- **THEN** 请求返回 422/400，状态不变

#### Scenario: Returned request is visible to the applicant

- **WHEN** 审批人退回到 Applicant
- **THEN** Applicant 能看到退回意见、审批人与时间
- **AND** 可以修改并重新提交

### Requirement: Approval visibility MUST be scoped

待办与详情 SHALL 只对提交者、持有对应审批权限的审批人以及组织管理员可见；无权用户 MUST 收到 403，且不得泄露提交是否存在。

#### Scenario: Other department member is denied

- **WHEN** 同组织其他部门成员请求审批详情
- **THEN** 请求返回 403
- **AND** 响应不含正文、标题或审批意见

#### Scenario: Applicant sees only their submissions

- **WHEN** Applicant 请求自己的审批列表
- **THEN** 只返回本人提交的请求

### Requirement: Approval actions MUST produce audit and activity events

提交、通过、退回与驳回 MUST 写入 Activity 与审计事件，载荷包含请求 ID、阶段、决策、审批人与时间，不包含正文或令牌。

#### Scenario: Approval event payload

- **WHEN** First Approver 通过请求
- **THEN** Activity 增加 `approval.first.approved` 事件
- **AND** 事件载荷不含文档正文

#### Scenario: No email in this version

- **WHEN** 审批状态变化
- **THEN** 系统不发送邮件
- **AND** 审批人与 Applicant 通过服务端 Activity/待办状态感知变化