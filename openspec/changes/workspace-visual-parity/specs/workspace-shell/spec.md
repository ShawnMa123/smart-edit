# Spec Delta

## Purpose

Defines the hierarchy and presentation of the workspace shell — the standing environment band, a document header restricted to real metadata, the page rendering of the editor, the standing save and lock status band, the version timeline and its info block, the assistant tab frame, empty-state structure, and how those layers behave on a narrow viewport — so the surface looks like the reference product without ever implying facts the build does not hold.

## ADDED Requirements

### Requirement: Workspace shell provides a standing environment band

The workspace SHALL present a persistent environment band that states the demo boundary of this build, so the operator never has to open a panel to learn what the data is.

#### Scenario: First load

- **WHEN** the operator opens the workspace
- **THEN** a standing environment band MUST exist directly below the top bar
- **AND** it MUST state in words that the data is synthetic/demo, that AI does not replace approval, and that version history is stored in this browser only
- **AND** that statement MUST NOT require opening an assistant tab to become visible

#### Scenario: Panel switching or scrolling

- **WHEN** the operator switches panes or scrolls the editor
- **THEN** the environment band MUST remain visible with unchanged content

### Requirement: Shell does not present unauthenticated identity

The shell SHALL NOT present a user, organisation or member list as if an authenticated session existed, because this build has no authentication.

#### Scenario: No identity data

- **WHEN** the workspace cannot obtain an authenticated user or organisation from the backend
- **THEN** the top bar MUST NOT show a person name, avatar or organisation name as the "current identity"
- **AND** it MUST identify the session neutrally (for example local demo session)
- **AND** it MUST NOT offer a member-management entry that pretends to work

### Requirement: Document header leads with document identity and real metadata

The document header SHALL identify the document first and SHALL list only metadata the system actually holds.

#### Scenario: Header content

- **WHEN** the operator views the document header
- **THEN** it MUST show the document path, the title and a business-status word tag
- **AND** the meta line MAY show character count, version count, draft revision, save state and content source
- **AND** fields the system does not hold (counterparties, template number, participating organisations) MUST NOT appear as sample values

#### Scenario: Technical details

- **WHEN** the meta line includes a content digest, a browser storage key or a lock lease
- **THEN** those facts MUST be collapsed behind a details control
- **AND** before expansion they MUST NOT occupy the header's main line

#### Scenario: A metadata value is missing

- **WHEN** a business field has no data source
- **THEN** the field MUST be omitted or shown as not provided
- **AND** it MUST NOT be filled with a placeholder example

### Requirement: Editor renders as a page without changing audit input

The editor SHALL render the document as a page on a canvas, and that presentation SHALL NOT change the text the audit receives.

#### Scenario: Page structure

- **WHEN** the operator views the editor pane
- **THEN** the document MUST render inside a centred page container with explicit page margins
- **AND** the page MUST carry a header and a footer showing the document identifier, a working-copy marker and the current version or snapshot marker

#### Scenario: Presentation does not affect the audit

- **WHEN** the document content is unchanged and only the page presentation applies
- **THEN** the projected text, the character count and the snapshot digest MUST be byte-identical to the values before this presentation change
- **AND** the audit request body MUST not change because of presentation

#### Scenario: Editing behaviour is unchanged

- **WHEN** the operator selects text in the page or uses the toolbar
- **THEN** the selection projection and the toolbar active state MUST match the previous behaviour
- **AND** the page container MUST NOT block keyboard input or a visible focus indicator

### Requirement: Edit and save status band stays visible

The editor SHALL keep one status band visible at all times, and that band SHALL state the save state, the snapshot it refers to and the lock state without inventing either.

#### Scenario: Normal editing

- **WHEN** the operator edits the draft
- **THEN** the status band MUST show the current version or snapshot identifier
- **AND** it MUST show the save state in words (saving, saved, save failed, conflict, local only)
- **AND** it MUST show the edit-lock state or state explicitly that the lock state is unknown

#### Scenario: Save conflict

- **WHEN** the server refuses a save
- **THEN** the status band wording MUST express the same fact as the conflict panel
### Requirement: Version sidebar is a timeline with a real-metadata info block

The version sidebar SHALL present versions as a timeline with a non-colour current marker, and its document information block SHALL list only metadata the system holds.

#### Scenario: Identifying the current version

- **WHEN** the sidebar lists several versions
- **THEN** the current version MUST carry a word marker in addition to any background treatment
- **AND** every entry MUST show its version label, creation time and content digest

#### Scenario: Document information block

- **WHEN** the operator views the document information block at the bottom of the sidebar
- **THEN** it MUST list only real metadata (at least one of document identifier, storage locality, version count, character count, draft revision)
- **AND** it MUST NOT show sample participating organisations, a sample workspace or claims such as "shared across organisations"

### Requirement: Assistant pane uses short tabs and a separate capability label

The assistant pane SHALL keep the reference tab set on one row and SHALL express each tab's implementation status as a separate label rather than inside the tab name.

#### Scenario: Tab row at desktop width

- **WHEN** the assistant pane is 352 pixels wide
- **THEN** the four tabs MUST render as short labels on a single row
- **AND** they MUST NOT wrap onto several rows because of label length

#### Scenario: Capability status

- **WHEN** a tab is fixture-backed or not implemented
- **THEN** that status MUST be presented by a separate label or statement
- **AND** selecting the tab MUST state its limitation
- **AND** it MUST NOT render sample answers, sample findings or sample citations

#### Scenario: Pane footnote

- **WHEN** the operator views the assistant pane
- **THEN** the pane MUST carry a single fixed footnote stating that results are bound to a fixed snapshot and that the assistant does not approve or submit

### Requirement: Empty states offer the next action

The workspace SHALL render an empty state with a title, a reason and the primary next action instead of a bare paragraph of grey text.

#### Scenario: Version history is empty

- **WHEN** no version has been captured yet
- **THEN** the sidebar MUST show an empty-state title, a short explanation and the capture entry point
- **AND** it MUST state that history is stored in this browser only

#### Scenario: Audit has not run

- **WHEN** the session has no audit result yet
- **THEN** the assistant pane MUST show an audit empty state with a title, a scope summary and the run entry point
- **AND** explanatory text MUST NOT displace the run entry point as the main element

### Requirement: Narrow viewport keeps the same shell layers

The workspace SHALL keep the shell layers reachable when the viewport is narrower than the three-pane breakpoint.

#### Scenario: Narrow load

- **WHEN** the viewport is narrower than the three-pane breakpoint
- **THEN** the top bar, the environment band, the document header and the edit status band MUST remain visible or reachable
- **AND** the three panes MUST stay reachable through the same switcher
- **AND** the page MUST remain readable within the available width without horizontal scrolling
- **AND** the surface MUST NOT claim both "saved to server" and "conflict" at the same time