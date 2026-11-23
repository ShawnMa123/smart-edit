# Spec Delta

## Purpose

Defines the explicit Demo data mode: a default-off switch that activates browser-local sample collaboration data, a persistent demo banner, isolated stores and a reset path. It exists so the workspace can show a complete demo surface without pretending that authentication, organisation membership or approval services are real.

## ADDED Requirements

### Requirement: Demo data mode is explicit and default off

The workspace SHALL offer an explicit `Demo data` switch and SHALL keep the honest mode active until the operator turns it on.

#### Scenario: First load

- **WHEN** the workspace loads without a persisted demo-mode choice
- **THEN** the workspace MUST start in honest mode with the neutral `Local demo session`
- **AND** it MUST NOT show sample users, organisations, memberships or approvals
- **AND** it MUST NOT show the demo banner

#### Scenario: Toggle on

- **WHEN** the operator turns `Demo data` on
- **THEN** the workspace MUST switch the first-batch modules to sample data
- **AND** it MUST persist the choice for the same browser
- **AND** it MUST show the demo banner defined below

### Requirement: Demo mode is announced by a persistent banner

The workspace SHALL make the sample-data boundary visible whenever demo mode is active.

#### Scenario: Banner content

- **WHEN** demo mode is active
- **THEN** a persistent banner MUST state that users, organisations and approvals are sample data
- **AND** it MUST state that this is not real authentication or a real workflow
- **AND** the banner MUST remain visible across shell, pane and dialog changes

#### Scenario: Banner absent in honest mode

- **WHEN** demo mode is off
- **THEN** the demo banner MUST NOT be rendered

### Requirement: Demo state is browser-local and reset-able

Demo state SHALL live in browser-local storage and SHALL be resettable without touching real draft, version or activity data.

#### Scenario: Persistence

- **WHEN** the operator reloads while demo mode is on
- **THEN** the demo identity, comments, approval and demo activity MUST remain available
- **AND** they MUST remain separate from the real activity store

#### Scenario: Reset demo data

- **WHEN** the operator chooses `Reset demo data` and confirms
- **THEN** the demo collaboration/activity state MUST return to its seeded sample values
- **AND** the real draft, version history and real activity MUST remain unchanged

### Requirement: Demo mode has no network side effects

Demo actions SHALL NOT call a backend service or claim a real server receipt.

#### Scenario: Sample collaboration action

- **WHEN** the operator switches demo identity, comments, invites a guest or advances the sample approval
- **THEN** the action MUST write only to the browser-local demo store
- **AND** it MUST NOT issue a backend request for that action
- **AND** any receipt MUST be labeled `Simulated`

### Requirement: Turning demo mode off restores honest mode

The workspace SHALL return to the existing honest behavior when the demo switch is turned off.

#### Scenario: Switch off

- **WHEN** the operator turns `Demo data` off
- **THEN** the top bar MUST return to the neutral `Local demo session`
- **AND** People, Approval and Comments MUST return to their explicit unavailable placeholders
- **AND** Activity MUST return to the real browser-local activity log
- **AND** the demo banner MUST disappear