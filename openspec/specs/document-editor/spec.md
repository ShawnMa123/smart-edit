# document-editor Specification

## Purpose
Defines the three-pane editing workspace and the audit round trip an operator performs inside it:
what each pane shows, how a document snapshot is captured and identified, what the audit request
sends, and — most importantly — what the screen must refuse to claim when a check did not actually
run. It exists so a demo of `agent-normalize` can be honest about its own coverage.

## Requirements

### Requirement: Workspace shows the three panes together

The workspace SHALL present version history, the document editor and the AI assistant as three
side-by-side panes, following the geometry of the reference prototype.

#### Scenario: Desktop viewport
- **WHEN** the viewport is at least 1366 pixels wide
- **THEN** the version history, the editor and the assistant pane MUST all be visible at once
- **AND** the editor pane MUST occupy the flexible middle column

#### Scenario: Narrow viewport
- **WHEN** the viewport is narrower than the three-pane breakpoint
- **THEN** the workspace MUST offer pane switching between the same three panes
- **AND** MUST NOT hide a pane without offering a way to reach it

### Requirement: Editor holds the document text and reports unsaved change

The editor SHALL be the single source of the document text used for snapshots and audits, and SHALL
make an unsaved change visible.

#### Scenario: Editing
- **WHEN** the operator types in the editor
- **THEN** the workspace MUST mark the document as having unsaved changes
- **AND** MUST update the character count

#### Scenario: After a snapshot
- **WHEN** a snapshot is captured from the current text
- **THEN** the editor MUST clear the unsaved-change marker
- **AND** the snapshot MUST record exactly the text that was present when it was taken

### Requirement: Version history is local and immutable

Version history SHALL let the operator capture snapshots and restore them without ever rewriting
history.

#### Scenario: Capture a version
- **WHEN** the operator captures a version
- **THEN** the history MUST gain one entry carrying a label, a creation time, a content digest and
  the snapshot text
- **AND** the list MUST show the newest entry first

#### Scenario: Restore an older version
- **WHEN** the operator restores an earlier version
- **THEN** the editor MUST load that version's text as an unsaved draft
- **AND** the history MUST remain unchanged until a new version is captured
- **AND** the restored text MUST NOT overwrite any existing entry

#### Scenario: History is browser-local
- **WHEN** the operator opens the workspace in a new browser session on the same machine
- **THEN** the previously captured versions MUST still be listed
- **AND** the workspace MUST state that history is stored in this browser only

### Requirement: Every version and snapshot is identified by a content digest

The workspace SHALL identify document content by a deterministic digest so a report can be bound to
the exact text it was produced from.

#### Scenario: Digest is deterministic
- **WHEN** the same document text is snapshotted twice
- **THEN** both snapshots MUST carry the same digest

#### Scenario: Digest changes with content
- **WHEN** any character of the document changes
- **THEN** the digest of the new snapshot MUST differ from the previous one

### Requirement: Audit submits a fixed snapshot

The audit SHALL run against an immutable copy of the document taken at the moment the operator asks
for it.

#### Scenario: Starting an audit
- **WHEN** the operator activates `Run spec audit`
- **THEN** the workspace MUST freeze a snapshot containing the text, its digest, the originating
  version identifier and the capture time
- **AND** MUST submit that frozen text to the pipeline without re-reading the editor afterwards

#### Scenario: Editing while an audit runs
- **WHEN** the operator edits the document while an audit is in flight
- **THEN** the running audit MUST continue against the frozen snapshot
- **AND** the resulting report MUST be presented as bound to that snapshot's digest, not to the
  current text

#### Scenario: The audited digest is displayed
- **WHEN** a report is rendered
- **THEN** the panel MUST show the digest of the snapshot the report was produced from

### Requirement: Audit scope is disclosed

The panel SHALL state which checks were performed and which were not, on every result it renders.

#### Scenario: Scope block after a completed run
- **WHEN** a report is rendered
- **THEN** the panel MUST name the checks that ran (normalization-stage field checks defined by the
  field dictionary: required presence, value format, length)
- **AND** MUST name the checks that did not run in this build: semantic consistency checks,
  customer/bank template clause checks, and regulatory coverage

#### Scenario: Scope is not buried
- **WHEN** the operator reads the result panel
- **THEN** the scope disclosure MUST be visible without opening a dialog or a secondary tab

### Requirement: Field checks are reported only when extraction ran

The panel SHALL gate field-level results on the stage that produces them, so an incomplete run is
never presented as a defect list for the customer's document.

#### Scenario: Extraction did not complete
- **WHEN** the extraction stage's report is not `done`
- **THEN** the panel MUST state that field checks did not run, and MUST show that stage's reason
- **AND** MUST NOT list `missing` fields as document defects
- **AND** MUST NOT display a pass state

#### Scenario: Fixture-backed extraction
- **WHEN** the extraction stage's reason indicates that candidates came from a fixture rather than a
  model provider
- **THEN** the panel MUST show that the run used a fixture
- **AND** MUST keep the results visually distinct from a provider-backed run

#### Scenario: Extraction completed
- **WHEN** the extraction and normalization stages both report `done`
- **THEN** the panel MUST list the field checks with each field's status, notes and located source
  where available

### Requirement: Reports are bound to a snapshot and expire

The panel SHALL mark a report stale as soon as the document no longer matches the audited snapshot.

#### Scenario: Document edited after a report
- **WHEN** the current text digest differs from the digest a rendered report is bound to
- **THEN** the panel MUST mark the report as stale and say it cannot be used for approval
- **AND** MUST offer to re-audit the current snapshot

#### Scenario: Stale results are still readable
- **WHEN** a report is stale
- **THEN** the previous findings MUST remain readable with their original digest
- **AND** MUST NOT be silently discarded or re-labelled as current

### Requirement: Absence of findings is never reported as compliance

The panel SHALL describe a zero-finding result as "no findings in the checks that ran" and SHALL
never present it as a pass or as compliance.

#### Scenario: Zero findings
- **WHEN** a completed report contains no findings
- **THEN** the panel MUST state that no findings were produced by the checks that ran
- **AND** MUST display the standing note that no findings does not mean legally compliant and that
  jurisdictional applicability was not assessed

#### Scenario: Findings present
- **WHEN** a report contains findings
- **THEN** the panel MUST list each finding's identifier, source, severity, message, evidence and
  related field keys
- **AND** MUST show per-severity counts

### Requirement: Audit failures are stated as failures

The panel SHALL render a failed audit as a failure with a reason, never as an empty or passing
result.

#### Scenario: Server refusal
- **WHEN** the audit request is refused with a machine-readable error code
- **THEN** the panel MUST show the failure and a message derived from that code
- **AND** MUST offer to retry

#### Scenario: Transport failure or timeout
- **WHEN** the request fails in transport or exceeds the client timeout
- **THEN** the panel MUST show the failure with the elapsed time
- **AND** MUST state that no conclusion was produced

### Requirement: Unimplemented assistant tabs are visible but labelled

The assistant pane SHALL keep the reference tab set and SHALL mark the tabs this build cannot serve.

#### Scenario: Opening the assistant pane
- **WHEN** the operator opens the assistant pane
- **THEN** the audit tab MUST be available
- **AND** the knowledge, automation and legal tabs MUST be present but marked as not implemented in
  this build

#### Scenario: Selecting an unimplemented tab
- **WHEN** the operator selects an unimplemented tab
- **THEN** the pane MUST show that the capability is not implemented
- **AND** MUST NOT render sample answers, findings or citations

### Requirement: Document actions state what this build can do

The workspace SHALL show the document actions the reference prototype offers, SHALL make the actions
this build can perform available, and SHALL mark the ones it cannot perform.

#### Scenario: Actions the build can perform
- **WHEN** the operator views the document header or footer
- **THEN** file import and rich-text formatting MUST be available actions
- **AND** activating file import MUST open the file chooser and MUST NOT state that it is unavailable

#### Scenario: Actions the build cannot perform
- **WHEN** the operator views the document header or footer
- **THEN** export and approval actions MUST be present but marked as not implemented
- **AND** activating one MUST state that it is unavailable rather than appearing to succeed

### Requirement: Status is never conveyed by colour alone

The workspace SHALL make every status legible without relying on colour, and SHALL be operable from
the keyboard.

#### Scenario: Status rendering
- **WHEN** any status (stage status, field status, finding severity, staleness) is displayed
- **THEN** it MUST carry a text label in addition to any colour treatment

#### Scenario: Keyboard operation
- **WHEN** the operator uses only the keyboard
- **THEN** every pane, tab and the audit action MUST be reachable and activatable
- **AND** the focused element MUST be visibly indicated
