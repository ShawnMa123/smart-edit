# Spec Delta

## MODIFIED Requirements

### Requirement: Editor holds the document text and reports unsaved change

The editor SHALL hold the text the operator edits, SHALL treat the server draft as the authoritative saved state, and SHALL make unsaved, saving, saved and conflict states visible.

#### Scenario: Editing

- **WHEN** the operator types in the editor
- **THEN** the workspace MUST mark the document as having unsaved changes
- **AND** MUST update the character count

#### Scenario: Automatic save

- **WHEN** the operator stops typing after the configured debounce
- **THEN** the workspace MUST save the current text against the draft revision it was based on
- **AND** MUST show a saving state followed by a saved state only after the host accepts the write
- **AND** MUST NOT report saved when the host rejected the write

#### Scenario: After a successful save

- **WHEN** the host accepts a draft save
- **THEN** the editor MUST clear the unsaved-change marker
- **AND** a snapshot taken afterwards MUST record exactly the text that is at the saved head

#### Scenario: Save conflict

- **WHEN** the host rejects a save because the draft head moved
- **THEN** the workspace MUST show a conflict state
- **AND** MUST keep the local content available as a recovery draft
- **AND** MUST NOT silently replace the editor content with the server head

#### Scenario: After a snapshot

- **WHEN** a snapshot is captured from the current text
- **THEN** the snapshot MUST record exactly the text that was present when it was taken
- **AND** the snapshot MUST NOT be presented as a saved draft revision unless the host accepted that text

### Requirement: Version history is local and immutable

Version history SHALL let the operator capture snapshots and restore them without ever rewriting history, and restoring content on a server-backed draft SHALL create a new draft revision.

#### Scenario: Capture a version

- **WHEN** the operator captures a version
- **THEN** the history MUST gain one entry carrying a label, a creation time, a content digest and
  the snapshot text
- **AND** the list MUST show the newest entry first

#### Scenario: Restore an older version

- **WHEN** the operator restores an earlier version
- **THEN** the editor MUST load that version's text as an unsaved draft
- **AND** the workspace MUST save it as a new draft revision rather than overwriting an existing one
- **AND** the history MUST remain unchanged until a new version is captured
- **AND** the restored text MUST NOT overwrite any existing entry

#### Scenario: History is browser-local

- **WHEN** the operator opens the workspace in a new browser session on the same machine
- **THEN** the previously captured versions MUST still be listed
- **AND** the workspace MUST state that history is stored in this browser only