# Spec Delta

## Purpose

定义 assistant 的 Automation tab 在**只有 fixture run core** 时如何可用、如何展示 run/result/proposal、如何执行 accept/apply/undo，以及如何诚实标注未实现的 automation 能力。它不新增后端生成能力，只把现有合同接到用户能在预期位置使用的界面。

## ADDED Requirements

### Requirement: Automation tab 必须可用并标注 fixture-only

The assistant pane SHALL make the Automation tab selectable and SHALL label it as fixture-only rather than not implemented.

#### Scenario: Opening the assistant pane

- **WHEN** the operator opens the assistant pane
- **THEN** the Automation tab MUST be present and selectable
- **AND** it MUST be labelled as fixture-only, not as not implemented

#### Scenario: Selecting Automation

- **WHEN** the operator selects the Automation tab
- **THEN** the pane MUST render the automation run surface
- **AND** MUST NOT render a generic “not implemented” placeholder for Automation

### Requirement: Automation tab 必须创建并轮询 run

The Automation tab SHALL submit the implemented fixture rewrite task as a run and SHALL show its current status and stage while it is active.

#### Scenario: Creating a fixture run

- **WHEN** the operator activates the fixture-run action on a document with a server draft
- **THEN** the UI MUST submit a `rewrite/replace_text` run
- **AND** it MUST show the returned run status and stage
- **AND** it MUST NOT show a proposal before the run succeeds

#### Scenario: Polling to a terminal state

- **WHEN** the run becomes succeeded, failed, cancelled or timed out
- **THEN** the UI MUST stop polling
- **AND** it MUST show the terminal status and any error or outcome

#### Scenario: Cancelling an active run

- **WHEN** the run is queued or running
- **THEN** the operator MUST be able to request cancellation
- **AND** the UI MUST show the resulting terminal status

### Requirement: Result 必须按 outcome 展示

The Automation tab SHALL render the immutable run result according to its outcome, and SHALL NOT fabricate a proposal when the outcome is not `proposal_ready`.

#### Scenario: Proposal outcome

- **WHEN** the result outcome is `proposal_ready`
- **THEN** the tab MUST show the proposal preview, risk flags and applicability
- **AND** MUST show the result limitations, including fixture-backed status

#### Scenario: Business outcome without a proposal

- **WHEN** the result outcome is `needs_clarification`, `needs_handoff` or `unable_to_process`
- **THEN** the tab MUST show the outcome and its details
- **AND** MUST NOT show or invent a proposal, candidate or citation

### Requirement: Apply 与 Undo 必须是显式动作

The Automation tab SHALL require explicit accept, apply and undo actions, and SHALL show the host receipt instead of claiming a write before the host accepted it.

#### Scenario: Accept then apply

- **WHEN** the operator accepts a proposal and then applies it
- **THEN** accept MUST only change disposition
- **AND** apply MUST send the current draft revision and lock
- **AND** the tab MUST show the returned application receipt and new revision

#### Scenario: Protected-fact risk

- **WHEN** a proposal carries protected-fact risk flags
- **THEN** apply MUST remain unavailable until the operator explicitly acknowledges those risks
- **AND** the acknowledgement MUST be sent with the apply request

#### Scenario: Undo conflict

- **WHEN** undo is rejected because the draft moved
- **THEN** the tab MUST show the conflict
- **AND** MUST NOT overwrite the newer document content

### Requirement: 未实现的 automation 能力必须列出

The Automation tab SHALL state which automation capabilities remain unimplemented, and SHALL NOT present fixture behavior as a complete automation assistant.

#### Scenario: Reading the capability boundary

- **WHEN** the operator views the Automation tab
- **THEN** it MUST state that extract, compare, fill, model rewrite, API mapping and voice are not implemented
- **AND** it MUST state that the implemented path is fixture-backed and does not call a model

#### Scenario: Unsupported task

- **WHEN** the current backend rejects an unsupported task type
- **THEN** the tab MUST present the rejection as an explicit limitation
- **AND** MUST NOT render sample output for that task

### Requirement: 错误与空态必须可理解

The Automation tab SHALL distinguish a missing server draft, a transport failure, a rejected run, and a run that produced no proposal.

#### Scenario: Missing draft or lock

- **WHEN** the document draft or edit lock is unavailable
- **THEN** the tab MUST explain that the fixture run cannot start
- **AND** MUST NOT show a proposal action as if it were available

#### Scenario: Transport or contract failure

- **WHEN** a run, result or apply request fails
- **THEN** the tab MUST show the failure code and a retry path where safe
- **AND** MUST NOT present stale output as the result of the failed request

### Requirement: 状态与动作必须可访问

The Automation tab SHALL expose run status, outcomes and actions with readable text and keyboard-operable controls, not colour alone.

#### Scenario: Status announcement

- **WHEN** run status or stage changes
- **THEN** the status MUST be available as readable text and announced to assistive technology
- **AND** completed, failed and cancelled states MUST be distinguishable without colour

#### Scenario: Keyboard operation

- **WHEN** the operator navigates the Automation tab by keyboard
- **THEN** the tab, run action, cancel, accept, apply and undo controls MUST be reachable and operable