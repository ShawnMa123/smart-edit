# Spec Delta

## Purpose

定义 automation 任务的异步运行与结果合同：任务被创建为可轮询的 run，产出不可变 result，并在发布前经过依赖核验、protected facts 检查与服务端 Reviewer。本 capability 当前只实现 `rewrite` 的确定性 `replace_text` 生成，其他任务类型必须失败关闭。

## ADDED Requirements

### Requirement: 运行创建返回可轮询的异步运行

The system SHALL create an automation run asynchronously and return a run identifier and initial status without returning a generated result inline.

#### Scenario: Creating a run

- **WHEN** an authorized user submits a supported automation task
- **THEN** the response MUST be `202` with a run id, `status=queued` and a `Location` for that run
- **AND** the response MUST NOT include a proposal, candidate set or final result

#### Scenario: Polling a run

- **WHEN** the user reads a run they are authorized to access
- **THEN** the response MUST include its current status and stage
- **AND** the result id MUST appear only after the run succeeded

### Requirement: 未实现的任务类型必须失败关闭

The system SHALL accept only task types implemented in this build, and MUST reject every other task type instead of queueing or partially processing it.

#### Scenario: Supported rewrite task

- **WHEN** the user submits `task_type=rewrite` with the implemented `replace_text` intent
- **THEN** the run MUST be accepted

#### Scenario: Unsupported task type

- **WHEN** the user submits `extract`, `fill`, `define_variable`, `compare`, `compose_import`, `map_api` or `voice_command`
- **THEN** the request MUST be rejected with an explicit not-implemented error
- **AND** no run or result MUST be created

### Requirement: 运行状态与终态不可覆盖

An automation run SHALL move through explicit statuses and stages, and a terminal status MUST NOT be overwritten by a late worker result.

#### Scenario: Normal completion

- **WHEN** a run completes processing and publishes a result
- **THEN** its status MUST become `succeeded`
- **AND** its stage MUST become `done`

#### Scenario: Late result after failure or cancellation

- **WHEN** a run is already `failed`, `cancelled` or `timed_out`
- **THEN** a later worker completion MUST NOT change the terminal status
- **AND** MUST NOT publish a result

### Requirement: 取消、超时与发布原子竞争

Cancellation, deadline expiry and successful publication SHALL compete through an atomic state transition; the first committed terminal transition SHALL win.

#### Scenario: Cancel before publish

- **WHEN** the user cancels a queued or running run before publication commits
- **THEN** the run MUST become `cancelled`
- **AND** no result MUST be published

#### Scenario: Deadline passed

- **WHEN** a run reaches its deadline before publication
- **THEN** the run MUST become `timed_out`
- **AND** a late publish attempt MUST be rejected

#### Scenario: Publish wins

- **WHEN** publication commits before a cancel request
- **THEN** the cancel request MUST report the run's existing terminal status
- **AND** MUST NOT rewrite the result

### Requirement: 每个运行至多一个不可变结果

A succeeded run SHALL have exactly one immutable result carrying completion, outcome, payload and limitations.

#### Scenario: Proposal result

- **WHEN** a supported rewrite run finishes successfully
- **THEN** the result MUST carry `completion=complete` and `outcome=proposal_ready`
- **AND** its payload MUST be a `ChangeProposal`

#### Scenario: Business outcome without a proposal

- **WHEN** the run cannot produce a proposal because more information is required or the request is out of scope
- **THEN** the result MUST carry `needs_clarification`, `needs_handoff` or `unable_to_process`
- **AND** MUST NOT fabricate a proposal id

#### Scenario: Re-reading a result

- **WHEN** the user reads a result after it was published
- **THEN** its outcome, payload and limitations MUST remain unchanged

### Requirement: 运行创建必须幂等

The system SHALL require an idempotency key when creating a run, and SHALL return the original run for a replay of the same key and request.

#### Scenario: Replaying the same creation

- **WHEN** the same idempotency key and same request are replayed
- **THEN** the system MUST return the original run id
- **AND** MUST NOT create a second run

#### Scenario: Reusing a key with another body

- **WHEN** the same idempotency key is reused with a different request body
- **THEN** the system MUST reject it as an idempotency conflict

### Requirement: 运行上下文必须绑定依赖并可过期

An automation run SHALL bind the document, draft revision, content digest, variables version, authorization version, generator version and reviewer version it used, and SHALL record them as dependencies.

#### Scenario: Dependency changed

- **WHEN** the draft, variables, authorization, generator or reviewer version changes after a result is published
- **THEN** the result or its proposal MUST be reported as stale or unavailable
- **AND** MUST NOT be applied as current

#### Scenario: Reading dependencies

- **WHEN** an authorized user reads a result
- **THEN** the dependencies actually used by that run MUST be queryable

### Requirement: protected facts 必须在发布前检查

The system SHALL deterministically compare protected facts in the source range and the proposed replacement, and SHALL expose any change as risk flags before a proposal can be applied.

#### Scenario: Polishing changes a fact

- **WHEN** a `polish` or `clarify` operation changes an amount, currency, date, party, negation, obligation or legal reference
- **THEN** the result MUST be rejected or require clarification
- **AND** MUST NOT publish an applicable proposal

#### Scenario: Substantive clause replacement

- **WHEN** a `replace_clause` operation changes a protected fact
- **THEN** the proposal MUST carry a substantive risk flag
- **AND** application MUST require approved source references or an explicit risk acknowledgement

### Requirement: Reviewer 必须由服务端生成并绑定提案

The system SHALL run a server-side Reviewer before publishing a proposal, persist its receipt, and revalidate that receipt when the proposal is applied.

#### Scenario: Review passes

- **WHEN** structure, anchors, quote, protected facts and variable closure pass review
- **THEN** the system MUST persist a passing receipt bound to the proposal and its context
- **AND** only then publish the proposal

#### Scenario: Review fails

- **WHEN** the Reviewer returns repair or abstain after at most one repair attempt
- **THEN** the run MUST NOT publish an applicable proposal

#### Scenario: Receipt mismatch at apply

- **WHEN** the stored review receipt is missing or no longer matches the proposal/context
- **THEN** apply MUST be rejected
- **AND** MUST NOT change the draft

### Requirement: 运行与读取必须执行 capability 检查

Creating or reading a run SHALL require the `read` and `use_ai` capabilities, while applying its proposal SHALL require `edit` and the current document lock.

#### Scenario: Missing AI capability

- **WHEN** a principal without `use_ai` submits a run
- **THEN** the request MUST be rejected
- **AND** no run MUST be created

#### Scenario: Cross-user access

- **WHEN** a principal requests another principal's run, result or proposal
- **THEN** the system MUST return the same not-found response used for an unknown resource

### Requirement: 运行不得产生外部副作用或伪造模型输出

An automation run SHALL NOT submit approvals, send external messages, publish rules, change authorization or call an external business system; fixture-backed output MUST be labelled as such.

#### Scenario: Fixture run

- **WHEN** a run uses the deterministic fixture generator
- **THEN** the result and proposal MUST be labelled fixture-backed
- **AND** MUST NOT claim that a model or external source verified the content

#### Scenario: Successful run

- **WHEN** any run succeeds
- **THEN** only its run, result, dependencies, review and audit state MUST change
- **AND** no approval, external request or permission change MUST occur