# Spec Delta

## Purpose

定义 automation 写入路径的最小可观察合同：不可变提案、人工接受与机器应用分离、基于基线的过期判定、幂等的原子应用与可校验撤销。它存在的目的是让「建议」和「已写入」成为两个明确状态，而不是把 UI 预览或模型输出当成正文修改。

## ADDED Requirements

### Requirement: 提案不可变且绑定基线

A change proposal SHALL be immutable after publication and SHALL carry the baseline it was generated from, including the document, draft revision, content digest, variable version and authorization context.

#### Scenario: Reading a proposal

- **WHEN** an authorized user reads a published proposal
- **THEN** the response MUST include its baseline identifiers, operations, preview and review receipt
- **AND** the proposal content MUST NOT change after publication

#### Scenario: Baseline mismatch

- **WHEN** the current draft revision or content digest differs from the proposal baseline
- **THEN** the proposal MUST be reported as stale
- **AND** MUST NOT be applicable

### Requirement: 接受与应用是两种不同状态

The system SHALL distinguish a human accept/reject decision from the host's application result; accepting a proposal MUST NOT write the document.

#### Scenario: Accepting without applying

- **WHEN** a user accepts a proposal
- **THEN** only its disposition MUST change to accepted
- **AND** the document revision MUST remain unchanged
- **AND** its application status MUST remain not applied

#### Scenario: Applying an accepted proposal

- **WHEN** the host successfully applies an accepted proposal
- **THEN** the application status MUST change only because the host returned a receipt
- **AND** the client or model MUST NOT be able to set that status directly

### Requirement: 过期提案不可应用

The system SHALL derive applicability at read and apply time from the current draft, variable version, source state, authorization and expiry, and SHALL reject a proposal that is not current.

#### Scenario: Dependency changed before apply

- **WHEN** the draft head, variables, template, source state or authorization changes after a proposal is published
- **THEN** the proposal MUST become stale or unavailable
- **AND** an apply request MUST be rejected without writing

### Requirement: 应用必须校验锁、基线与风险确认

The host SHALL apply a proposal only when the requester holds the current edit lock with a valid lease and fencing token, the draft revision matches, and every required risk has been explicitly acknowledged.

#### Scenario: Missing or stale lock

- **WHEN** an apply request presents no lock, another owner's lock, an expired lease or a stale fencing token
- **THEN** the host MUST reject the apply
- **AND** MUST NOT change content, variables or proposal state

#### Scenario: Incomplete risk acknowledgement

- **WHEN** an apply request omits a risk code the proposal requires
- **THEN** the host MUST reject the apply
- **AND** MUST NOT apply any operation

### Requirement: 应用是原子的

The host SHALL update document content, variables, proposal state, application receipt and audit/outbox event in one atomic operation, and SHALL leave no partial result when any step fails.

#### Scenario: Failure during apply

- **WHEN** any required write fails during apply
- **THEN** the host MUST roll back the whole application
- **AND** MUST NOT leave a changed draft, consumed proposal, checkpoint or receipt

#### Scenario: Successful apply

- **WHEN** apply succeeds
- **THEN** the host MUST create a new draft revision and checkpoint
- **AND** MUST record the previous revision, new revision, content digest and actor in an application receipt

### Requirement: 应用必须幂等且每个提案至多成功一次

The system SHALL require an idempotency key for apply, SHALL return the original receipt for a replay of the same key and request, and SHALL prevent a second successful application of the same proposal.

#### Scenario: Replaying the same request

- **WHEN** an apply with the same idempotency key and same request is replayed
- **THEN** the host MUST return the original receipt
- **AND** MUST NOT create a second revision

#### Scenario: A different key targets an applied proposal

- **WHEN** a different idempotency key targets a proposal that was already applied
- **THEN** the host MUST reject the request as already applied
- **AND** MUST identify the existing receipt without applying again

#### Scenario: Same key with different content

- **WHEN** the same idempotency key is reused with a different request body
- **THEN** the host MUST reject it as an idempotency conflict

### Requirement: 撤销只针对当前最新一次自动化应用

The system SHALL allow undo only for the most recent successful automation application whose new revision is still the current draft head, and SHALL create a new revision instead of deleting history.

#### Scenario: Undo on the current head

- **WHEN** the user undoes the latest applied automation change and the draft head still equals its new revision
- **THEN** the host MUST write the inverse change as a new revision
- **AND** MUST record a reversal receipt
- **AND** MUST preserve the original receipt and every earlier checkpoint

#### Scenario: Content changed after apply

- **WHEN** a human edit or another application advanced the draft head after the receipt
- **THEN** undo MUST be rejected as an undo conflict
- **AND** MUST NOT overwrite the newer content

### Requirement: replace_text 必须锚定真实原文

A `replace_text` proposal SHALL target a verified range of the baseline snapshot, SHALL carry the expected original text digest, and SHALL NOT overlap another operation or cross a protected structural boundary.

#### Scenario: Anchor or quote mismatch

- **WHEN** the anchored range no longer resolves to the expected original text
- **THEN** the host MUST reject the apply
- **AND** MUST NOT perform a fuzzy match or write at a different position

#### Scenario: Overlapping operations

- **WHEN** a proposal contains two operations whose ranges overlap
- **THEN** the proposal MUST be rejected before any write

### Requirement: 未经复核的提案不可应用

A proposal SHALL carry a machine review receipt whose verdict is pass, and the host SHALL refuse to apply a proposal without one.

#### Scenario: Missing or failed review

- **WHEN** a proposal has no review receipt or a verdict other than pass
- **THEN** the host MUST reject the apply
- **AND** MUST NOT change the document

### Requirement: 应用不产生外部副作用

Applying a proposal SHALL NOT submit an approval, send an external message, publish a rule, change authorization or call an external business system.

#### Scenario: Automation apply

- **WHEN** an apply succeeds
- **THEN** only the draft and its recorded receipt/audit state MUST change
- **AND** no approval, external request or permission change MUST occur