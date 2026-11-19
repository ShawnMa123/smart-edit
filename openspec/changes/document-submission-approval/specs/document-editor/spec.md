# Spec Delta

## MODIFIED Requirements

### Requirement: Document actions state what this build can do

The workspace SHALL show the document actions the reference prototype offers, SHALL make the actions this build can perform available to authorised roles, and SHALL mark the ones it cannot perform. `Submit new version` SHALL perform a real server submission when the principal holds `approval.submit`; approval actions SHALL open the approval inbox or status for principals holding the matching approval permission.

#### Scenario: Actions the build can perform

- **WHEN** the operator views the document header or footer
- **THEN** file import and rich-text formatting MUST be available actions
- **AND** activating file import MUST open the file chooser and MUST NOT state that it is unavailable
- **AND** `Submit new version` MUST be an available action for an Applicant with a loaded server draft

#### Scenario: Actions the build cannot perform

- **WHEN** the operator views the document header or footer
- **THEN** export MUST be present but marked as not implemented
- **AND** activating export MUST state that it is unavailable rather than appearing to succeed
- **AND** approval actions MUST NOT claim to be unavailable when the principal holds the matching approval permission

#### Scenario: Submitted document is read-only

- **WHEN** the document has a submission in `pending_first`, `pending_second` or `approved`
- **THEN** the editor MUST present the document as read-only
- **AND** MUST NOT offer `Start editing` as a successful action

#### Scenario: Returned submission is editable again

- **WHEN** the latest submission is `returned`
- **THEN** the editor MUST show the return reason and allow the Applicant to acquire the lock and edit
- **AND** a new submission MUST be required to restart approval