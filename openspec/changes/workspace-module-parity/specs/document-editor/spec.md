# Spec Delta

## ADDED Requirements

### Requirement: Version comparison compares two captured versions

The workspace SHALL let the operator compare two captured versions and show their textual differences without generating an AI summary.

#### Scenario: Comparing two versions

- **WHEN** the operator selects exactly two captured versions and activates Compare
- **THEN** the workspace MUST show both version labels, capture times and content digests
- **AND** it MUST show per-block added, removed and changed text derived from the projected plain text
- **AND** it MUST NOT generate an AI summary or infer content that is absent from either version

#### Scenario: Invalid selection

- **WHEN** the operator has not selected exactly two captured versions
- **THEN** the Compare action MUST be disabled or explain that two versions are required
- **AND** it MUST NOT open a comparison with substituted or empty versions

#### Scenario: No textual differences

- **WHEN** the two selected versions project to identical text
- **THEN** the comparison MUST state that there are no textual differences
- **AND** it MUST NOT claim that the versions are identical in every respect

### Requirement: Version comparison never mutates history or the draft

The comparison SHALL be read-only with respect to captured history and the current working document.

#### Scenario: After a comparison

- **WHEN** the operator closes a comparison
- **THEN** the captured version list, the current editor draft and the server draft revision MUST be unchanged
- **AND** no new version entry MUST be created by the comparison
- **AND** the comparison MUST NOT require a network request to render