# Spec Delta

## ADDED Requirements

### Requirement: Editor footer exposes lock and submission controls

The editor SHALL expose the reference footer action set so lock and submission controls are reachable without leaving the document pane.

#### Scenario: Footer actions rendered

- **WHEN** the operator views the editor pane
- **THEN** the footer MUST show `Release lock`, `Start editing` and `Submit new version`
- **AND** each control MUST have an accessible name and be reachable by keyboard

### Requirement: Lock controls change the real lock state

The footer lock controls SHALL operate on the existing document lock rather than only changing local copy.

#### Scenario: Lock held

- **WHEN** this session holds the edit lock
- **THEN** `Release lock` MUST be enabled and `Start editing` MUST be disabled
- **AND** the status band MUST continue to state that the lock is held by this session

#### Scenario: Lock released

- **WHEN** the operator releases the lock
- **THEN** the server lock MUST be released and the status band MUST change to the released/unknown wording
- **AND** `Start editing` MUST become enabled and `Release lock` MUST become disabled

#### Scenario: Start editing

- **WHEN** the operator activates `Start editing` while no lock is held
- **THEN** the workspace MUST acquire the real document lock
- **AND** the status band MUST update to show the held lock without claiming a save

### Requirement: Shared version submission is not faked

The workspace SHALL keep the reference `Submit new version` position while making clear that shared submission is unavailable in this build.

#### Scenario: Opening submission

- **WHEN** the operator activates `Submit new version`
- **THEN** a dialog MUST state that shared version submission is not available in this build
- **AND** it MUST offer a real `Capture browser-local version` action
- **AND** it MUST NOT show a success receipt or claim the document was submitted

#### Scenario: Capturing instead of submitting

- **WHEN** the operator chooses `Capture browser-local version`
- **THEN** the existing browser-local version capture MUST run
- **AND** the dialog MUST close
- **AND** the version list and current-version marker MUST update as they do for a normal capture

### Requirement: Document header exposes comments and keeps unavailable actions honest

The document header SHALL offer the reference comments entry and SHALL continue to mark actions this build cannot perform.

#### Scenario: Header actions

- **WHEN** the operator views the document header
- **THEN** `Import file`, `Comments`, `Export` and `Start approval` MUST be present
- **AND** `Import file` MUST open the file chooser
- **AND** `Comments` MUST open an explicit placeholder that names the missing comment service and renders no sample comments
- **AND** `Export` and `Start approval` MUST be marked unavailable and MUST NOT appear to succeed

#### Scenario: Formatting is not an unavailable header action

- **WHEN** the operator views the document header
- **THEN** the header MUST NOT mark formatting as unavailable
- **AND** rich-text formatting MUST remain available through the editor toolbar and keyboard shortcuts

### Requirement: Block format control preserves heading and paragraph capability

The toolbar SHALL group paragraph and heading levels into one block-format control without removing any formatting capability.

#### Scenario: Choosing a block format

- **WHEN** the operator chooses Paragraph, Heading 1, Heading 2 or Heading 3 from the block-format control
- **THEN** the current block MUST receive that format
- **AND** the projected text MUST use the same heading prefix rules as before
- **AND** the control MUST reflect the current block format

### Requirement: Grouped table controls remain reachable

The toolbar SHALL keep table insertion and row/column operations reachable when table controls are grouped.

#### Scenario: Table actions

- **WHEN** the operator opens the grouped table controls
- **THEN** insert table and the row/column operations MUST remain available
- **AND** the operations MUST be keyboard reachable
- **AND** the existing table behavior MUST be unchanged