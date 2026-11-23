# Spec Delta

## MODIFIED Requirements

### Requirement: Document actions state what this build can do

The workspace SHALL show the document actions the reference prototype offers, SHALL make the actions
this build can perform available to authorised roles, and SHALL mark the ones it cannot perform.
`Submit new version` SHALL perform a real server submission when the principal holds
`approval.submit`; approval actions SHALL open the Approval view when the principal holds an approval
permission. The document header SHALL show the latest submission status instead of a fixed `Draft`
label.

#### Scenario: Actions the build can perform
- **WHEN** the operator views the document header or footer
- **THEN** file import and rich-text formatting MUST be available actions
- **AND** activating file import MUST open the file chooser and MUST NOT state that it is unavailable
- **AND** `Submit new version` MUST be available to an Applicant with a loaded server draft and lock
- **AND** an approval action MUST be available to a principal holding `approval.first` or `approval.second`

#### Scenario: Actions the build cannot perform
- **WHEN** the operator views the document header or footer
- **THEN** export MUST be present but marked as not implemented
- **AND** activating export MUST state that it is unavailable rather than appearing to succeed
- **AND** approval MUST NOT be marked as unavailable in an authenticated PG session

#### Scenario: Submitted document is read-only
- **WHEN** the document has a submission in `pending_first`, `pending_second` or `approved`
- **THEN** the editor MUST present the document as read-only
- **AND** MUST NOT offer `Start editing` as a successful action

#### Scenario: Returned submission is editable again
- **WHEN** the latest submission is `returned`
- **THEN** the editor MUST show the return reason and allow the Applicant to acquire the lock and edit
- **AND** a new submission MUST be required to restart approval

#### Scenario: Header reflects the real status
- **WHEN** the latest submission is pending, approved, returned or rejected
- **THEN** the document header MUST show that status
- **AND** MUST NOT show a fixed `Draft` label