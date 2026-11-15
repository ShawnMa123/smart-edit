# Spec Delta

## MODIFIED Requirements

### Requirement: Unimplemented assistant tabs are visible but labelled

The assistant pane SHALL keep the reference tab set and SHALL mark only the tabs this build cannot serve.

#### Scenario: Opening the assistant pane

- **WHEN** the operator opens the assistant pane
- **THEN** the audit tab MUST be available
- **AND** the knowledge tab MUST be available and MUST NOT be marked as not implemented
- **AND** the automation tab MUST be available and MUST be labelled fixture-only, not as not implemented
- **AND** the legal tab MUST be present but marked as not implemented in this build

#### Scenario: Selecting an unimplemented tab

- **WHEN** the operator selects an unimplemented tab
- **THEN** the pane MUST show that the capability is not implemented
- **AND** MUST NOT render sample answers, findings or citations

#### Scenario: Selecting the automation tab

- **WHEN** the operator selects the automation tab
- **THEN** the pane MUST provide the fixture-backed automation run surface
- **AND** MUST state which automation capabilities remain unimplemented
- **AND** MUST NOT render sample answers, findings or citations for those capabilities