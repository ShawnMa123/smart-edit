# Spec Delta

## Purpose

Defines the first batch of sample collaboration behavior shown when Demo data mode is on: a labeled demo identity switcher, a sample organisation/member directory, a local approval state machine, sample comment threads and a seeded demo activity log. Every behavior is local sample data, never a real identity, ACL or approval.

## ADDED Requirements

### Requirement: Demo identity switcher is labeled

The shell SHALL expose the sample identities only while demo mode is active and SHALL label them as demo data.

#### Scenario: Demo identity shown

- **WHEN** demo mode is active
- **THEN** the top bar MUST show the current sample identity with a visible `Demo identity` marker
- **AND** it MUST offer a switcher listing the sample identity names and roles
- **AND** switching identity MUST update the sample collaboration permissions without changing the real editor/lock/audit principal

#### Scenario: Honest mode unchanged

- **WHEN** demo mode is off
- **THEN** the top bar MUST show the neutral `Local demo session`
- **AND** it MUST NOT show a sample person or organisation as the current identity

### Requirement: Demo identity controls sample collaboration permissions

The sample identity SHALL gate the demo-only actions consistently with its sample role.

#### Scenario: Applicant

- **WHEN** the current demo identity is the applicant
- **THEN** starting a sample approval MUST be available
- **AND** approving the applicant's own request MUST NOT be available

#### Scenario: Bank operations and compliance

- **WHEN** the current demo identity is the bank operations or compliance reviewer
- **THEN** approving or rejecting the sample approval at that reviewer's step MUST be available when the step is active
- **AND** approving the requester's own request MUST NOT be available

#### Scenario: External counsel guest

- **WHEN** the current demo identity is the external counsel guest
- **THEN** viewing sample members and comments MUST remain available
- **AND** starting or approving the sample approval MUST NOT be available

### Requirement: People shows a sample directory

The People dialog SHALL show sample organisations, members and guest access while demo mode is active.

#### Scenario: Directory content

- **WHEN** the operator opens People in demo mode
- **THEN** the dialog MUST show sample organisation names, member names, roles and verification/guest status
- **AND** it MUST label the directory as sample data
- **AND** it MUST NOT claim that the members were authenticated by a real identity service

#### Scenario: Guest invitation

- **WHEN** the operator invites the external counsel sample guest or revokes that guest
- **THEN** the change MUST update only the browser-local demo state
- **AND** the resulting status MUST be labeled as simulated

### Requirement: Approval uses a local sample state machine

The Approval dialog SHALL demonstrate the reference workflow using local sample state and SHALL label every receipt as simulated.

#### Scenario: Start approval

- **WHEN** the applicant starts the sample approval
- **THEN** the state MUST move from `DRAFT` to `IN_REVIEW`
- **AND** the first reviewer step MUST become active
- **AND** no backend request or real approval MUST occur

#### Scenario: Reviewer decision

- **WHEN** the active reviewer approves or rejects the request
- **THEN** the sample state MUST advance to the next reviewer or become `APPROVED`/returned
- **AND** the decision MUST record the sample actor and time
- **AND** the decision must be labeled `Simulated`

#### Scenario: Handoff receipt

- **WHEN** the sample approval is approved and the operator confirms the sample handoff
- **THEN** the state MUST become `HANDED_OFF`
- **AND** the receipt MUST state that no external system received the document
- **AND** it MUST remain browser-local

#### Scenario: Submit new version in demo mode

- **WHEN** the operator activates `Submit new version` while demo mode is on
- **THEN** the workspace MUST enter the sample approval flow instead of the honest “not available” dialog
- **AND** it MUST NOT claim a shared version was submitted to a server

### Requirement: Comments use sample threads

The Comments dialog SHALL show sample comment threads and SHALL keep new comments in the demo store.

#### Scenario: Seeded threads

- **WHEN** the operator opens Comments in demo mode
- **THEN** the dialog MUST show sample authors, text, version references, anchors and unresolved/resolved status
- **AND** the data MUST be labeled as sample data

#### Scenario: Add and resolve

- **WHEN** the operator adds a comment, optionally with the current selection quote, or marks a thread resolved
- **THEN** the change MUST update only the demo state
- **AND** the author MUST be the current demo identity
- **AND** no comment service request MUST be issued

### Requirement: Demo activity is seeded and separated from real activity

Demo mode SHALL show sample activity and notifications without changing the real browser-local activity log.

#### Scenario: Seeded demo activity

- **WHEN** the operator opens Activity in demo mode
- **THEN** it MUST show seeded sample events with sample actors and timestamps
- **AND** it MUST label the list as sample data
- **AND** it MUST NOT merge those entries into the real activity list

#### Scenario: Demo Inbox

- **WHEN** the operator opens Inbox in demo mode
- **THEN** notifications MUST be derived from demo activity
- **AND** they MUST identify the sample actor/event without claiming a real assignment
- **AND** marking them read MUST stay local

#### Scenario: Real activity unchanged

- **WHEN** demo mode is on and the operator imports, saves, captures or runs an audit
- **THEN** the real activity log MAY still receive the real operation
- **AND** the demo list MUST remain visibly separate from that real log