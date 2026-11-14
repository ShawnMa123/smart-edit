# Spec Delta

## MODIFIED Requirements

### Requirement: Unimplemented assistant tabs are visible but labelled

The assistant pane SHALL keep the reference tab set and SHALL mark the tabs this build cannot serve;
the knowledge tab MUST be available and functional.

#### Scenario: Opening the assistant pane

- **WHEN** the operator opens the assistant pane
- **THEN** the audit tab MUST be available
- **AND** the knowledge tab MUST be available and MUST NOT be marked as not implemented
- **AND** the automation and legal tabs MUST be present but marked as not implemented in this build

#### Scenario: Selecting an unimplemented tab

- **WHEN** the operator selects an unimplemented tab
- **THEN** the pane MUST show that the capability is not implemented
- **AND** MUST NOT render sample answers, findings or citations

#### Scenario: Selecting the knowledge tab

- **WHEN** the operator selects the knowledge tab
- **THEN** the pane MUST provide the knowledge Q&A surface
- **AND** answers MUST carry their support level and citations, or state why they are absent