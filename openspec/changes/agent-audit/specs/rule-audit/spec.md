# Spec Delta

## Purpose

Defines the standards audit group: it audits one fixed document snapshot against a resolved, versioned
rule bundle **plus the customer's template** (field expectations, required/controlled/optional clauses,
internal declarations), accounts for every check it planned, and answers whether a specific protected
operation may proceed. It is deterministic by construction, never judges business merit or legal
applicability, and makes partial coverage impossible to mistake for a clean result.

## ADDED Requirements

### Requirement: Audit runs against one fixed snapshot

The system SHALL audit exactly one immutable snapshot and bind every result to it.

#### Scenario: Snapshot is frozen before evaluation
- **WHEN** an audit starts
- **THEN** the system MUST fix the document text, the field values, the schema version, the rule bundle
  versions and the engine version into one audit context
- **AND** the resulting report MUST record the content digest of that snapshot

#### Scenario: Document changes during the run
- **WHEN** the document is modified while an audit is in flight
- **THEN** the report MUST remain bound to the snapshot it started from
- **AND** the report MUST be marked stale once the current snapshot digest differs
- **AND** the system MUST NOT re-point existing findings at the new text

#### Scenario: Same inputs produce the same report
- **WHEN** the same snapshot, the same rule bundle versions and the same engine version are audited
  twice
- **THEN** the two reports MUST be equal apart from run identifiers and timestamps
- **AND** this MUST hold without any model call

### Requirement: Coverage is planned before it is executed

The system SHALL enumerate the checks it intends to perform before evaluating them, and SHALL account
for every planned check.

#### Scenario: Every planned check receives a state
- **WHEN** an audit completes
- **THEN** each planned check unit MUST carry one of `pass`, `finding`, `not_applicable`,
  `needs_input`, `unable_to_assess`, `failed`
- **AND** the counts of those six states MUST sum to the number of planned units

#### Scenario: Unrun units are not dropped
- **WHEN** a planned unit cannot run (missing bundle, timeout, crashed handler)
- **THEN** it MUST appear with `failed`, `needs_input` or `unable_to_assess` and a reason code
- **AND** MUST NOT be omitted from the report

#### Scenario: Empty plan is a configuration failure
- **WHEN** the resolved rule set yields no check units
- **THEN** the run MUST be reported as failed for configuration reasons
- **AND** MUST NOT be reported as a report with no findings

### Requirement: Required fields are distinguished, never silently passed

The system SHALL separate "the document does not contain it" from "we could not confirm it" from
"we failed to read it".

#### Scenario: Field absent from the document
- **WHEN** a field required by the rule bundle has no value in the snapshot
- **THEN** the unit MUST produce a finding whose rule reference identifies the requirement
- **AND** the finding MUST NOT be suppressed by the rule's own applicability requirements

#### Scenario: Field present but unconfirmed
- **WHEN** a required field carries a value that a human has not confirmed
- **THEN** the unit MUST be `needs_input`
- **AND** MUST NOT be `pass`, and MUST NOT be reported as absent

#### Scenario: Field could not be parsed
- **WHEN** a required field failed to parse or its extraction failed
- **THEN** the unit MUST be `failed` with a reason code distinguishing it from absence

### Requirement: Field values are checked against the published schema

The system SHALL evaluate value type, format, length unit and character set against the published
schema, keeping the original value and its source.

#### Scenario: Value violates its declared type or format
- **WHEN** a value does not satisfy its declared type (for example a non-decimal amount)
- **THEN** the finding MUST identify the field, the violated schema check and the original value

#### Scenario: Length is counted in a declared unit
- **WHEN** a length rule applies
- **THEN** the unit of length (`code_point`, `grapheme` or `byte`) MUST be explicit
- **AND** an encoding failure MUST be reported as a failure, MUST NOT be counted as length zero

#### Scenario: Character set comes from an approved catalogue
- **WHEN** a character-set rule applies
- **THEN** it MUST reference a catalogued character set
- **AND** user-supplied regular expressions MUST NOT be accepted as a character-set rule

### Requirement: Amount rules are exact and currency-aware

The system SHALL evaluate monetary rules with exact decimal arithmetic and an explicit currency.

#### Scenario: Comparing amounts
- **WHEN** a rule compares two amounts
- **THEN** both sides MUST share one confirmed currency
- **AND** the comparison MUST use exact decimal arithmetic, MUST NOT use floating point

#### Scenario: Malformed numeric input
- **WHEN** a value contains scientific notation, NaN, infinity or more decimal places than allowed
- **THEN** the unit MUST report the value as invalid with a reason code
- **AND** the audit MUST NOT round the value on the document's behalf

#### Scenario: Unknown amounts are not zero
- **WHEN** one side of a comparison is missing or unconfirmed
- **THEN** the unit MUST be `needs_input` or `unable_to_assess`
- **AND** MUST NOT treat the missing side as zero

#### Scenario: Required projection is unavailable
- **WHEN** a rule needs a derived value this build does not compute (for example a subtotal)
- **THEN** the unit MUST be `unable_to_assess` with an explicit reason
- **AND** MUST NOT be approximated by a model or reported as `pass`

### Requirement: Date rules use business dates and real calendars

The system SHALL evaluate date rules against the audit's business date and a real calendar.

#### Scenario: Impossible date
- **WHEN** a value claims a date that does not exist in the calendar
- **THEN** the unit MUST report the value as invalid

#### Scenario: Ordering between dates
- **WHEN** a rule requires one date to precede another (for example expiry after issue)
- **THEN** the unit MUST evaluate the ordering on the parsed dates
- **AND** MUST NOT substitute the run date for a missing business date

#### Scenario: Unsupported calendar feature
- **WHEN** a rule requires a working-day or holiday calendar this build has no versioned source for
- **THEN** the unit MUST be `unable_to_assess`
- **AND** MUST NOT guess a calendar

### Requirement: Rule evaluation is three-valued and pure

The system SHALL evaluate rules with true / false / unknown semantics and without side effects.

#### Scenario: Unknown applicability
- **WHEN** a rule's applicability cannot be decided from the snapshot context
- **THEN** the unit MUST be `needs_input` or `unable_to_assess` according to the reason
- **AND** MUST NOT be `pass` and MUST NOT be `not_applicable`

#### Scenario: Unknown expression result
- **WHEN** an applicable rule's expression evaluates to unknown
- **THEN** the unit MUST be `needs_input` or `unable_to_assess`
- **AND** MUST NOT be `pass`

#### Scenario: Engine purity
- **WHEN** rules are evaluated
- **THEN** evaluation MUST NOT perform network calls, model calls, filesystem writes or execute
  user-supplied code
- **AND** the engine version MUST be recorded in the report

#### Scenario: Deterministic findings cite a rule
- **WHEN** a unit produces a finding
- **THEN** the finding MUST reference the rule id and version that produced it

### Requirement: Only published rules apply and conflicts are visible

The system SHALL resolve rules from published bundle versions and SHALL surface integrity problems
instead of ignoring them.

#### Scenario: Unpublished bundle
- **WHEN** a bundle version is not published
- **THEN** its rules MUST NOT be evaluated

#### Scenario: Missing mandatory bundle
- **WHEN** a required rule bundle is absent for the document type
- **THEN** the affected units MUST be `failed` or `needs_input`
- **AND** the report MUST NOT be presented as a clean pass

#### Scenario: Conflicting mandatory rules
- **WHEN** two applicable published sources impose conflicting mandatory rules
- **THEN** the conflict MUST be reported
- **AND** protected operations MUST NOT be allowed on that snapshot

#### Scenario: Clients cannot remove mandatory rules
- **WHEN** an audit request is created
- **THEN** the request MUST NOT be able to drop mandatory rules or narrow the checked scope while
  claiming a full audit

### Requirement: Findings carry severity, gate type and an anchor

The system SHALL express each finding so a reviewer can act on it, and SHALL keep severity and gate
behaviour independent.

#### Scenario: Finding shape
- **WHEN** a finding is produced
- **THEN** it MUST include an identifier, the producing method (`deterministic` or `semantic`),
  a category, a severity of `critical` / `warn` / `info`, a gate type of `advisory` /
  `human_review` / `hard_block`, the rule reference, an anchor, evidence and a disposition state

#### Scenario: Severity does not decide blocking
- **WHEN** a finding has severity `critical`
- **THEN** that severity alone MUST NOT block an operation
- **AND** only the finding's gate type and the operation's policy decide blocking

#### Scenario: Model output can never hard-block
- **WHEN** a finding originates from a semantic (model) method
- **THEN** its gate type MUST NOT be `hard_block`
- **AND** such a finding MUST be treated as a contract violation

#### Scenario: Anchor cannot be resolved
- **WHEN** a finding's anchor no longer resolves in the snapshot
- **THEN** the anchor MUST NOT be guessed
- **AND** the finding MUST be reported as needing human location

### Requirement: Outcomes are aggregated without hiding gaps

The system SHALL summarise a report so that partial coverage can never read as a clean result.

#### Scenario: Outcome values
- **WHEN** a report is published
- **THEN** its outcome MUST be one of `findings_present`, `no_findings`, `needs_input`,
  `unable_to_assess`
- **AND** its completion MUST be `complete` only when every planned unit is `pass`, `finding` or
  `not_applicable`

#### Scenario: Mixed pass and failure
- **WHEN** some units pass and at least one unit is `failed`
- **THEN** the outcome MUST NOT be `no_findings`
- **AND** completion MUST be `partial`

#### Scenario: Everything is not applicable
- **WHEN** every planned unit is `not_applicable`
- **THEN** the outcome MUST be `unable_to_assess` with reason `no_applicable_checks`
- **AND** MUST NOT be presented as compliance or as a pass

#### Scenario: Zero findings is not compliance
- **WHEN** the outcome is `no_findings`
- **THEN** the report MUST state that no findings were produced by the checks that ran
- **AND** MUST NOT be presented as compliance, legality or approval

### Requirement: The gate answers per protected operation

The system SHALL decide a protected operation from the rules, the findings and the candidate snapshot,
and SHALL answer nothing broader than that operation.

#### Scenario: Decision values
- **WHEN** a gate decision is produced
- **THEN** it MUST contain a decision of `allowed` / `blocked` / `indeterminate`, the operation, the
  candidate snapshot digest, the policy revision, the evaluation time and reason codes

#### Scenario: Only deterministic rules hard-block
- **WHEN** findings with gate type `hard_block` exist for the operation
- **THEN** the decision MUST be `blocked` only if those findings came from deterministic rules
- **AND** semantic or advisory findings MUST NOT block

#### Scenario: Uncertainty never allows
- **WHEN** a required unit is `needs_input`, `unable_to_assess` or `failed`, or a mandatory rule is
  missing
- **THEN** the decision MUST be `blocked` or `indeterminate`, MUST NOT be `allowed`

#### Scenario: Draft saving is not a content gate
- **WHEN** the operation is `save_draft`
- **THEN** content rules MUST NOT block the save
- **AND** identity, edit permission and locking MUST still apply

#### Scenario: The candidate is what gets checked
- **WHEN** the operation targets a specific version (submit, approve, export, hand off, map)
- **THEN** the decision MUST bind the digest of the candidate that will be submitted
- **AND** the system MUST NOT trust client-supplied rule ids, statuses or report ids

#### Scenario: Decision is not a reusable token
- **WHEN** the document, the policy or the authorisation changes after a decision was produced
- **THEN** the decision MUST be considered stale
- **AND** the consuming operation MUST re-evaluate instead of reusing it

### Requirement: Human disposition is append-only

The system SHALL record human handling of findings as events and SHALL keep it distinct from fixing.

#### Scenario: Disposition values
- **WHEN** a human handles a finding
- **THEN** the recorded state MUST be `open`, `accepted`, `rejected` or `needs_human_review`
- **AND** each change MUST append an event carrying actor and time, MUST NOT rewrite earlier events

#### Scenario: Rejecting a critical finding needs a reason
- **WHEN** a `critical` finding is rejected
- **THEN** a reason MUST be required
- **AND** the rejection MUST NOT be treated as a rule waiver

#### Scenario: Accepting is not fixing
- **WHEN** a finding is accepted
- **THEN** the finding MUST remain visible in the report
- **AND** acceptance MUST NOT change the unit's state or the gate history

### Requirement: The audit does not judge business or law

The system SHALL restrict itself to evaluating published rules against the snapshot.

#### Scenario: No commercial judgement
- **WHEN** a value passes every applicable rule
- **THEN** the report MUST NOT claim the transaction is commercially reasonable or desirable

#### Scenario: Internal policy checks the declaration only
- **WHEN** an internal-policy rule requires a declaration (for example a lawful-source statement)
- **THEN** the unit MUST evaluate whether the declaration exists and satisfies the rule
- **AND** MUST NOT conclude that the underlying fact is true

#### Scenario: Out-of-scope questions are referred
- **WHEN** the question is regulatory applicability or legal interpretation
- **THEN** the report MUST refer it to the regulatory capability
- **AND** MUST NOT answer it as an audit finding

### Requirement: Evidence-chain checks guard the audit's own inputs

The system SHALL keep verifying that the values it audits are traceable, and SHALL fail loudly when
they are not.

#### Scenario: Overreach in the trail
- **WHEN** the run's trail contains `summarize`, `rewrite` or `drop`
- **THEN** the audit MUST produce a `fail` finding naming the entry
- **AND** the gate MUST NOT allow a protected operation on that snapshot

#### Scenario: Untraceable extracted value
- **WHEN** a field claims it was extracted but has no source, or its span cannot be located in its own
  file
- **THEN** the audit MUST produce a `fail` finding for that field

#### Scenario: Dangling finding anchor
- **WHEN** a finding references field keys that exist in neither `fields` nor `extra_fields`
- **THEN** the audit MUST produce a `fail` finding

#### Scenario: One checker crashes
- **WHEN** a single check raises an exception
- **THEN** the audit MUST record a `fail` item for that check with a reason
- **AND** the remaining checks MUST still run
- **AND** the run MUST NOT be reported as having no findings

### Requirement: Templates are a versioned audit basis

A template pack SHALL declare `template_id`, `version`, `published`, `content_sha256`, document types, a
counterparty, field expectations, clauses and internal declarations, plus the policy packs it belongs to.
Only published template versions take part in an audit, and the report MUST cite the `template_id`,
`version` and `content_sha256` it actually used.

#### Scenario: Published template is used and cited
- **WHEN** an audit runs on a published template version
- **THEN** the report MUST carry that template's `template_id`, `version` and `content_sha256`
- **AND** every template check MUST reference that version

#### Scenario: Unpublished template never applies
- **WHEN** the template directory holds a version with `published: false`
- **THEN** no check MUST use it
- **AND** if that leaves no usable template, the result MUST be `unable_to_assess` with a reason code

#### Scenario: Template change makes an old report stale
- **WHEN** the template version or digest differs from the one recorded in an existing report
- **THEN** the existing report MUST be marked stale with reason `template_changed`
- **AND** its conclusions MUST NOT be re-bound to the new template

### Requirement: Template resolution is unique or it is unable

The system SHALL resolve exactly one template from the document type, the counterparty and any
host-supplied template reference. Zero or several candidates MUST yield `unable_to_assess` with reason
`no_applicable_template` or `ambiguous_template`; the system MUST NOT guess, MUST NOT pick by load order,
and MUST NOT let a client override a published version.

#### Scenario: One candidate matches
- **WHEN** exactly one published template matches the document type and counterparty
- **THEN** the audit MUST use that template
- **AND** the report MUST record the resolution basis (document type, counterparty field and value)

#### Scenario: No candidate matches
- **WHEN** no published template matches
- **THEN** every template unit MUST be `unable_to_assess` with reason `no_applicable_template`
- **AND** no protected operation MUST be `allowed`

#### Scenario: Several candidates match
- **WHEN** two or more published templates match
- **THEN** the result MUST be `unable_to_assess` with reason `ambiguous_template`
- **AND** the report MUST list the candidate `{template_id, version}` pairs

#### Scenario: Client tries to change the template version
- **WHEN** a client submits a template reference whose version differs from the resolved one
- **THEN** the system MUST keep the host-resolved version
- **AND** MUST NOT change any rule or template version because of the request

### Requirement: Template field expectations are deterministic checks

Template field expectations SHALL be executed as deterministic checks: `allowed_values` (for example
"the settlement currency MUST be USD", "the origin country MUST be one of the listed values"),
conditional requirements that only apply when their condition holds, and cross-field consistency. Each
expectation MUST become its own planned unit referencing the template version, and an undecidable
expectation MUST NOT count as a pass.

#### Scenario: Currency outside the template's allowed values
- **WHEN** the template requires `USD` and the document states `EUR`
- **THEN** the unit MUST be `finding`
- **AND** its `gate_type` MUST come from the template/policy declaration, never from severity

#### Scenario: Origin country outside the allowed set
- **WHEN** the template lists allowed origin countries and the document value is not among them
- **THEN** the unit MUST be `finding` and MUST state the expected and actual values
- **AND** the anchor MUST point at that field

#### Scenario: Conditional requirement not triggered
- **WHEN** a field is required only while another condition holds, and that condition does not hold
- **THEN** the unit MUST be `not_applicable`
- **AND** MUST NOT produce a required-field finding

#### Scenario: Value not yet confirmed
- **WHEN** a field the expectation depends on is `unconfirmed`
- **THEN** the unit MUST be `needs_input`
- **AND** MUST NOT be `pass`

### Requirement: Policy combination conflicts are visible and block release

The system SHALL combine the base template with bank, customer and department policy packs into one
resolved policy, recording each pack's owner, version, validity window and source. Disagreements between
sources MUST be visible as conflicts, MUST NOT be settled by load order, and while a conflict is
unresolved the affected checks MUST be `unable_to_assess` and protected operations MUST NOT be `allowed`.

#### Scenario: Two sources gate one field differently
- **WHEN** a bank pack declares a field `hard_block` and a customer pack declares the same field `advisory`
- **THEN** the conflict MUST appear in the report's conflict list naming both sources
- **AND** the affected unit MUST be `unable_to_assess`
- **AND** `start_approval` MUST NOT be `allowed`

#### Scenario: Several rules for one field inside one pack
- **WHEN** a single pack carries both a hard rule and an advisory rule for one field
- **THEN** that MUST NOT be reported as a conflict
- **AND** both checks MUST run independently

#### Scenario: Mandatory policy pack is missing
- **WHEN** a policy pack the transaction requires is unpublished or absent
- **THEN** the affected checks MUST be `unable_to_assess` with a reason code
- **AND** the run MUST NOT read as "no applicable checks, therefore clean"

#### Scenario: Client tries to drop a mandatory rule
- **WHEN** a request excludes a mandatory rule or an entire policy pack
- **THEN** the exclusion MUST be ignored
- **AND** the verdict MUST still be computed from the policy that includes it

### Requirement: Internal-policy checks judge declarations only

Internal-policy checks SHALL decide only whether a declaration, field or controlled process record is
present and satisfies the template's condition. They MUST NOT conclude that funds are lawful or that the
transaction is genuine.

#### Scenario: Lawful-source declaration missing
- **WHEN** the template requires a lawful-source declaration and the document has none
- **THEN** the unit MUST be `finding` in the internal-policy category
- **AND** its waivability MUST come from the template, not from severity

#### Scenario: Declaration present
- **WHEN** the document carries the declaration and it satisfies the condition
- **THEN** the unit MUST be `pass`
- **AND** the report MUST NOT claim the funds or the transaction were verified

### Requirement: Template coverage is accounted for and inspectable

Template checks SHALL join the same plan as schema, rule and evidence units, and the plan total MUST be
conserved. The system SHALL expose a template health check that reports field evaluability, clause
locatability, vector completeness and conflicts, and whose exit code acts as the gate.

#### Scenario: Plan includes template units
- **WHEN** an audit runs on a template version
- **THEN** the plan MUST include that template's field and clause units
- **AND** the six unit states MUST sum to the planned total

#### Scenario: Template field cannot be evaluated
- **WHEN** a template declares a field type or expectation that cannot be evaluated
- **THEN** the health check MUST fail with a non-zero exit code
- **AND** the template MUST NOT be reported as publishable

#### Scenario: Controlled clause text cannot be located
- **WHEN** a controlled clause's text cannot be located in the template's own text
- **THEN** the health check MUST fail and name that clause
- **AND** the clause MUST NOT be skipped silently
