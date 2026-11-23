# Spec Delta

## Purpose

Defines the workspace's navigation shell: the desktop rail, the top-bar action cluster, the narrow-viewport entry points, the explicit placeholders for modules this build cannot serve, and the read-only implementation map. It exists so the surface can match the reference prototype's navigation without pretending that authentication, organisation membership or approval services exist.

## ADDED Requirements

### Requirement: Desktop navigation exposes the reference entry set

The workspace SHALL render a persistent desktop navigation rail with the reference entry set, so every module has a visible entry point.

#### Scenario: Desktop layout

- **WHEN** the viewport is at least the three-pane breakpoint
- **THEN** a fixed-width rail MUST be visible beside the workspace content
- **AND** it MUST contain entries for Document, Versions, Approval, Comments, People and Developer
- **AND** the active entry MUST carry a visible text label or accessible name in addition to colour

#### Scenario: Keyboard access

- **WHEN** the operator navigates by keyboard
- **THEN** every rail entry MUST be focusable and activatable
- **AND** the focused entry MUST have a visible focus indicator

### Requirement: Top bar exposes the reference action cluster without an identity

The top bar SHALL expose the reference actions while keeping the session neutral, because this build has no authenticated user or organisation.

#### Scenario: Top bar content

- **WHEN** the workspace loads
- **THEN** the top bar MUST show entries for Activity, People, Inbox and Developer
- **AND** it MUST identify the session with a neutral label rather than a person name, avatar or organisation
- **AND** activity and notification counts MUST reflect actual browser-local state, never fixed sample values

#### Scenario: Identity entry

- **WHEN** the operator activates the neutral session entry
- **THEN** the workspace MUST state that authentication is not configured in this build
- **AND** it MUST NOT display a sample user, role, email or organisation

### Requirement: Unavailable modules use explicit placeholders

The workspace SHALL represent modules without a backend capability by an explicit placeholder rather than by sample data or a success-looking action.

#### Scenario: Opening an unavailable module

- **WHEN** the operator activates People, Approval or Comments
- **THEN** the workspace MUST state that the module is not available in this build
- **AND** it MUST name the missing capability (for example authentication, organisation membership, approval workflow or comment service)
- **AND** it MUST NOT render sample members, organisations, approvers, comments or permissions

#### Scenario: Placeholder side effects

- **WHEN** an unavailable placeholder is open
- **THEN** activating its controls MUST NOT write data, change permissions or issue a network request

### Requirement: Developer entry is a read-only implementation map

The workspace SHALL provide a read-only implementation map that explains which reference modules are available, partial or unavailable in this build.

#### Scenario: Opening the implementation map

- **WHEN** the operator activates Developer
- **THEN** the workspace MUST show a table of reference module, current status and limitation
- **AND** it MUST distinguish available, partial and unavailable states in words
- **AND** it MUST NOT display invented API contracts or claim a missing backend exists

### Requirement: Narrow viewports keep the same entries reachable

The workspace SHALL expose the same navigation entries on narrow viewports without horizontal scrolling.

#### Scenario: Narrow layout

- **WHEN** the viewport is narrower than the three-pane breakpoint
- **THEN** the rail MAY collapse, but Document, Versions, Approval, Comments, People and Developer MUST remain reachable through the pane switcher or a menu
- **AND** the active entry MUST be indicated by an accessible state in addition to colour
- **AND** the workspace MUST remain usable without horizontal scrolling