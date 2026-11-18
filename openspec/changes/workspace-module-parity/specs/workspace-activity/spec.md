# Spec Delta

## Purpose

Defines a browser-local activity log and the notifications derived from it. The capability exists so operators can see what actually happened in this workspace without inventing server audit events, teammates or task assignments.

## ADDED Requirements

### Requirement: Activity records actual workspace operations

The workspace SHALL record an activity entry when a user-visible operation succeeds, so the activity log reflects real events rather than sample history.

#### Scenario: Operation recorded

- **WHEN** the operator completes an operation such as importing a file, saving a draft, capturing or restoring a version, starting an audit, asking the knowledge assistant or applying a template
- **THEN** the activity log MUST gain one entry containing the action, a short detail, the event time and the source `browser`
- **AND** the entry MUST use the neutral local session label rather than an invented person or organisation

#### Scenario: Operation fails

- **WHEN** an operation fails before producing its intended result
- **THEN** the activity log MUST record the failure as a failure, or omit it
- **AND** it MUST NOT record a success entry for that operation

### Requirement: Activity log is browser-local and bounded

The activity log SHALL persist in the browser and SHALL state its local scope, because this build has no server activity service.

#### Scenario: Reload

- **WHEN** the operator reloads the workspace in the same browser
- **THEN** previously recorded activity entries MUST still be listed
- **AND** the newest entry MUST appear first

#### Scenario: Scope statement

- **WHEN** the activity log is displayed
- **THEN** it MUST state that the history is stored in this browser only and is not a server audit trail
- **AND** it MUST NOT claim that the events were written to the backend

#### Scenario: Bounded history

- **WHEN** more than the configured maximum number of entries have been recorded
- **THEN** the oldest entries MUST be evicted so the log stays bounded
- **AND** the visible activity count MUST match the retained entries

### Requirement: Activity can be cleared explicitly

The workspace SHALL let the operator clear the local activity only after an explicit confirmation.

#### Scenario: Clear activity

- **WHEN** the operator chooses to clear activity and confirms
- **THEN** all local activity entries and the activity count MUST reset
- **AND** the version history, draft and audit results MUST remain unchanged

#### Scenario: Cancel clear

- **WHEN** the operator cancels the clear action
- **THEN** the activity entries MUST remain unchanged

### Requirement: Notifications derive only from real local events

The workspace SHALL present notifications as a view of actual local events, not as invented tasks or messages from other people.

#### Scenario: Opening notifications

- **WHEN** the operator opens Inbox
- **THEN** it MUST list only notifications derived from recorded activity or real local results
- **AND** each notification MUST identify the underlying event and its time
- **AND** it MUST NOT show a fabricated sender, assignee or task

#### Scenario: Unread count

- **WHEN** new notifications are created by real events
- **THEN** the top-bar count MUST increase
- **AND** marking them read MUST decrease the count without creating a server-side read receipt

### Requirement: Unavailable browser storage degrades visibly

The workspace SHALL remain usable when activity storage is unavailable or corrupt.

#### Scenario: Storage unavailable

- **WHEN** browser storage rejects a read or write
- **THEN** the workspace MUST state that activity is session-only or unavailable
- **AND** it MUST NOT silently claim that the events were saved
- **AND** it MUST continue to operate without a crash