# Spec Delta

## Purpose

Defines the language the interface speaks and where identity-bearing text comes from, so the demo presents English chrome consistently, never mixes languages inside one surface, and never substitutes example strings for stored document metadata.

## ADDED Requirements

### Requirement: Interface copy is English

Every piece of interface copy SHALL be written in English, independent of the language of the document being edited.

#### Scenario: Rendered chrome

- **WHEN** the operator views any surface (shell, panes, assistant tabs, dialogs, empty states, status and error notices)
- **THEN** headings, labels, buttons, helper text and notices MUST be English
- **AND** no single control MUST mix an English label with a non-English gloss

#### Scenario: Non-English document content

- **WHEN** the document being edited contains Chinese or any other non-English text
- **THEN** that text MUST remain exactly as authored inside the document
- **AND** the surrounding interface copy MUST stay English

### Requirement: The page declares its language

The document SHALL declare the interface language it actually renders.

#### Scenario: Page language attribute

- **WHEN** the workspace is served
- **THEN** the root document language MUST be declared as English
- **AND** the document title element MUST be English
- **AND** MUST NOT declare Chinese while rendering English copy

### Requirement: Assistant sessions are pinned to English

The assistant SHALL request the English locale and SHALL NOT fall back to non-English corpus text as interface copy.

#### Scenario: Opening the knowledge tab

- **WHEN** the operator opens the knowledge tab
- **THEN** the onboarding copy and suggested questions MUST be English
- **AND** the first question MUST create the session with the `en` locale

#### Scenario: Non-English source material

- **WHEN** the English corpus cannot answer a question
- **THEN** the panel MUST state that limitation in English
- **AND** MUST NOT render Chinese corpus text as interface copy
- **AND** MUST NOT translate a source silently while presenting it as a quotation

### Requirement: Document title and identifier come from stored metadata

The document header SHALL derive the title and identifier from stored document data, and SHALL NOT display example strings as if they were the document's own.

#### Scenario: Title from the draft

- **WHEN** the workspace has loaded a draft with a title
- **THEN** the header title MUST show that stored title
- **AND** when no title is stored it MUST use an English fallback such as Untitled document
- **AND** it MUST NOT append a translation or gloss

#### Scenario: Document path

- **WHEN** the header shows the document path
- **THEN** the path MUST use the stored document identifier
- **AND** it MUST NOT display an example reference such as `DG-2026-00417`