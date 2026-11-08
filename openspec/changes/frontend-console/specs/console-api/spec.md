# Spec Delta

## Purpose

Defines the HTTP boundary between the operator console and the pipeline: how a run is created,
how a stage is triggered, what a result read always contains, and how every refusal is expressed
as a machine-readable code. It implements the stage-triggering and observability requirements
already declared by `orchestration`; it adds only the client-facing contract those specs leave
unstated.

## ADDED Requirements

### Requirement: Run creation returns a reusable identifier

The system SHALL accept one run's source material and return an identifier that later stage
triggers and result reads address.

#### Scenario: Files submitted
- **WHEN** a client posts one or more files to `POST /runs`
- **THEN** the response MUST contain `thread_id`, the accepted `files` (each with `file_id`,
  `filename`, `sha256`) and an initial `stages` list
- **AND** the same `thread_id` MUST be usable by `POST /runs/{thread_id}/stages/{stage}` and
  `GET /runs/{thread_id}`

#### Scenario: Build capabilities are reported as data
- **WHEN** a run is created or read
- **THEN** the response MUST contain `supported_stages`, listing only the stages this build can
  execute
- **AND** a stage absent from that list MUST NOT be reported as executed, skipped or passing

#### Scenario: Pasted text submitted
- **WHEN** a client posts plain text instead of files
- **THEN** the response MUST contain a `thread_id` whose run has exactly one synthetic file entry
- **AND** the resulting parse MUST produce blocks with `page` and `bbox` equal to `null`

#### Scenario: Empty submission refused
- **WHEN** a client posts neither files nor text
- **THEN** the system MUST respond `400` with `code: "EMPTY_SUBMISSION"`
- **AND** MUST NOT create a run

### Requirement: Stage triggering executes the declared prerequisite chain

The system SHALL trigger a stage by executing the prerequisite chain that the stage registry
declares, in order, rather than running the requested stage alone.

#### Scenario: Full chain requested on a fresh run
- **WHEN** a client posts `stages/normalize` for a run whose `docs` and `_candidates` do not exist
- **THEN** the system MUST execute `parse`, then `extract`, then `normalize`
- **AND** the response MUST contain one `StageReport` per executed stage in that order

#### Scenario: Prerequisites already satisfied
- **WHEN** a client posts `stages/normalize` for a run whose `parse` report is already `done`
- **THEN** the system MUST NOT re-parse the files
- **AND** the response MUST still contain the existing `done` report for that stage
- **AND** the run's `fields` and `trail` MUST be unchanged by the request

#### Scenario: Re-triggering a stage whose output was consumed
- **WHEN** a client triggers `normalize` again on a run that already completed it
- **THEN** the system MUST refuse with `409 REFUSED` naming `_candidates` as the missing prerequisite
- **AND** the existing `fields` and `stages` MUST remain unchanged
- **AND** a client wanting a fresh audit MUST create a new run rather than re-trigger the stage

### Requirement: Result reads carry the full observable envelope

The system SHALL return the run's observable state in one response so a client never has to infer
completeness from a missing key.

#### Scenario: Result read after a stage run
- **WHEN** a client reads `GET /runs/{thread_id}`
- **THEN** the response MUST contain `thread_id`, `business_type`, `fields`, `extra_fields`,
  `findings`, `stages` and `trail`
- **AND** `stages` MUST include the report of every stage executed so far

#### Scenario: Stage reports cannot be omitted
- **WHEN** the system cannot assemble `stages` for an existing run
- **THEN** it MUST respond `500` with `code: "INCOMPLETE_RESULT"`
- **AND** it MUST NOT respond `200` with an empty or absent `stages` value

#### Scenario: Unnormalized candidates are exposed separately
- **WHEN** a result read happens after `extract` but before `normalize`
- **THEN** the response MUST expose the candidates under `_candidates`
- **AND** MUST NOT populate `fields` from them

### Requirement: Refusals are expressed as machine-readable codes

The system SHALL report every refusal with a stable `code` field, so clients branch on the code and
never on prose.

#### Scenario: Unregistered stage target
- **WHEN** a client triggers a stage that is not registered as a stage target
- **THEN** the system MUST respond `409` with `code: "unknown_stage"` and `registered` listing the
  valid targets

#### Scenario: Prerequisite cannot be satisfied
- **WHEN** a trigger's prerequisites are not satisfiable (for example `files` is absent)
- **THEN** the system MUST respond `409` with `code: "REFUSED"` and `missing` naming the absent keys
- **AND** MUST NOT respond with an empty result set

#### Scenario: Agent that cannot run standalone
- **WHEN** a client triggers an agent whose registry entry declares `standalone: false`
- **THEN** the system MUST respond `403` with `code: "NOT_STANDALONE"`
- **AND** MUST NOT execute it

### Requirement: Run state lifetime is explicit

The system SHALL scope run state to the server process until a durable checkpointer exists, and
report a vanished run as an error rather than as an empty run.

#### Scenario: Unknown run
- **WHEN** a client reads or triggers a `thread_id` the server does not hold
- **THEN** the system MUST respond `404` with `code: "unknown_run"`
- **AND** MUST NOT respond `200` with empty `fields` and empty `stages`

#### Scenario: Server restarted
- **WHEN** the server restarts and a client reuses a `thread_id` from before the restart
- **THEN** the system MUST respond `404` with `code: "unknown_run"`
- **AND** the response MUST state that run state is process-scoped

### Requirement: Absent model provider fails the extract stage loudly

The system SHALL fail `extract` with an explicit stage report when no model provider is configured,
and SHALL mark any fixture-backed substitute as such.

#### Scenario: No provider configured
- **WHEN** `extract` runs and no model provider is configured
- **THEN** the system MUST record `StageReport(stage="extract", status="failed")` with a `reason`
  naming the missing provider configuration
- **AND** MUST NOT return candidates produced by guessing, hard-coding or replaying a sample

#### Scenario: Fixture stub explicitly enabled
- **WHEN** the operator opts into the fixture-backed stub
- **THEN** the `extract` report `reason` MUST state that candidates came from a fixture
- **AND** the response MUST remain distinguishable from a real provider run by that `reason` alone