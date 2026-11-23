# Spec Delta

## Purpose

定义文档从可编辑草稿变成不可变提交版本的边界：提交时冻结正文与变量、绑定完整 revision、释放编辑锁，并在审批结束或退回前阻止继续修改。

## ADDED Requirements

### Requirement: Submission MUST freeze an immutable snapshot

提交 MUST 在提交瞬间冻结当前草稿的正文、变量、revision 与内容摘要；后续草稿变化 MUST NOT 改变已提交版本。

#### Scenario: Snapshot survives later draft edits

- **WHEN** Applicant 提交 revision 3，随后草稿保存为 revision 4
- **THEN** 该提交仍返回 revision 3 的正文与内容摘要
- **AND** 审批详情展示的是 revision 3 的快照

#### Scenario: Snapshot content is not re-read from the editor

- **WHEN** 提交成功后再读取审批详情
- **THEN** 正文来自服务端保存的提交快照
- **AND** 不依赖浏览器当前编辑内容

### Requirement: Submission MUST require the current draft and its lock

提交 MUST 校验提交者持有该草稿的有效编辑锁，并校验提交的 revision 与内容摘要仍与当前草稿一致。

#### Scenario: Valid submission

- **WHEN** 锁持有者以当前 revision 与摘要提交
- **THEN** 系统创建提交并返回提交 ID、状态与审批请求
- **AND** 当前编辑锁被释放

#### Scenario: Stale revision is rejected

- **WHEN** 提交携带的 revision 已被其他保存推进
- **THEN** 请求返回 409，且不创建提交
- **AND** 客户端必须重新加载草稿

#### Scenario: Missing or foreign lock is rejected

- **WHEN** 请求没有有效锁，或锁属于其他用户
- **THEN** 请求返回 403/409，且不创建提交

### Requirement: Submitted documents MUST be read-only until returned

存在进行中提交时，系统 MUST 阻止获取编辑锁或保存新草稿；审批通过后文档 MUST 保持只读；退回后 MUST 允许再次编辑。

#### Scenario: Editing while pending is blocked

- **WHEN** Applicant 在 `pending_first` 或 `pending_second` 期间尝试获取锁或保存
- **THEN** 请求返回 409，且草稿内容不变

#### Scenario: Returned submission unlocks editing

- **WHEN** 审批人退回提交
- **THEN** Applicant 可以重新获取锁并编辑
- **AND** 原提交与审批记录保持不可变

#### Scenario: Approved submission stays read-only

- **WHEN** 提交状态为 `approved`
- **THEN** 获取编辑锁与保存请求被拒绝

### Requirement: Applicant MUST see submission status and history

提交者 SHALL 能查看该文档的提交列表、当前状态与最近一次审批结果；历史提交 MUST NOT 被后续提交覆盖。

#### Scenario: Status after first approval

- **WHEN** First Approver 通过提交
- **THEN** Applicant 看到状态从 `pending_first` 变为 `pending_second`

#### Scenario: Resubmission creates a new record

- **WHEN** Applicant 在退回后再次提交
- **THEN** 系统创建新的 submission ID
- **AND** 上一次提交及其审批意见仍可查询

### Requirement: Submission MUST produce an activity event

提交成功 MUST 写入服务端 Activity 事件，载荷只包含提交 ID、文档 ID、revision 与状态，不包含正文或令牌。

#### Scenario: Submission event payload

- **WHEN** 提交成功
- **THEN** Activity 增加一条 `submission.created` 事件
- **AND** 事件载荷不包含文档正文