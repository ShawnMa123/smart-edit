# Tasks

> Artifacts are English per an explicit instruction (see `design.md` Open Questions 3).
> Group 0 must complete **before any code**: it decides ownership of field-value checks and signs off
> the two frozen-file edits. Everything here is deterministic — no model call anywhere.
>
> **Status (2026-11-08, second pass):** `0.2` is **done** — A approved the frozen edits as a set of
> purely additive, optional changes (recorded below); B and C countersigns are still outstanding and
> change nothing in the code, because nothing existing was modified. `0.1` (the `agent-verify` boundary)
> remains **open** and needs B. Everything else in this change is implemented and tested:
> **281 passed**, `scripts/audit_demo.py` and `python -m app.rules.doctor` both green.

## 0. Ownership and sign-off gate

- [ ] 0.1 Record the boundary with `agent-verify`: it authors rule bundles (business parameters,
  requirement lists); this group owns the engine, the coverage plan and the gate. Verify: the decision
  is written into `design.md` Open Questions 1 (replacing the question with an answer) and mirrored as a
  note in `agent-verify/tasks.md`; no rule-evaluation code exists in that change.
- [x] 0.2 Sign-off checklist for the frozen edits: `app/state.py` gains five `NotRequired` fields
  (`Issue.gate_type`, `Issue.target_operations`, `Issue.check_id`, `Issue.method`,
  `VerificationReport.audit`); `app/stages.py` gains the `audit` stage target and flips
  `AGENT_SPECS["agent4"].standalone` to `True`. Verify: `git diff` touches only those lines and all new
  fields are optional; three approvals recorded in the change.

  **Approval record (2026-11-08).** A approved and implemented. B / C countersign pending — they cannot
  be blocked by this diff: all five fields are `NotRequired`, nothing existing was renamed or removed,
  and the only behavioural change is that `agent4` becomes triggerable through the new `audit` target.
  Files touched: `app/state.py` (the `Issue` / `VerificationReport` blocks only), `app/stages.py`
  (`AGENT_SPECS["agent4"].standalone`, the new `audit` entry in `STAGE_TARGETS`, `AGENT_TARGETS`).
  Evidence: `tests/test_audit_node.py::test_agent4_resolves_to_the_audit_target`,
  `tests/test_api.py::test_agent4_is_standalone_through_the_audit_target`.

## 1. Schema binding and typed values

- [x] 1.1 `app/rules/schema.py`: project `app/configs/fields.yaml` into a schema bundle (field id, value
  type, `max_length`, `charset`, `precision`, `date_order`, `required`) plus a `schema_version` hash.
  Verify: test asserts all 15 fields project, the hash is stable across runs, and a broken config raises
  `FieldsConfigError` instead of yielding an empty schema.
- [x] 1.2 `app/audit/bind.py`: map `FieldValue` to an audit value using design D7 (absent / confirmed /
  unconfirmed / contract violation). Verify: table-driven test covering `missing`, `extracted` with a
  source, `inferred`, and `extracted` without a source.

## 2. Rule DSL and deterministic engine

- [x] 2.1 `app/rules/dsl.py`: the closed op set (`all`/`any`/`not`/`exists`/`compare`/`length`/
  `charset`/`contains_clause`) with structural validation. Verify: tests reject an empty `all`, `byte`
  length without `encoding`, `encoding` with a non-byte unit, unknown ops and extra properties.
- [x] 2.2 `app/rules/engine.py`: three-valued evaluation with the ordering schema → context →
  applicability → expression; every `unknown` maps to `needs_input` or `unable_to_assess`, never `pass`.
  Verify: truth-table tests for each op, plus the rule that a missing field used in `required_facts`
  cannot pre-empt its own required-field finding.
- [x] 2.3 Purity guard. Verify: test asserts the `app/rules` import graph contains neither `app.llm` nor
  an HTTP client, and that evaluation performs no filesystem writes.
- [x] 2.4 `app/rules/bundles.py`: load bundle files (`bundle_id`, `version`, `published`,
  `content_sha256`, rules) and evaluate only published versions. Verify: tests that an unpublished
  bundle is ignored, a missing mandatory bundle turns its units `failed`, and conflicting mandatory
  rules are reported.
- [x] 2.5 `app/rules/bundles/guarantee.yaml`: POC rule pack — required presence, amount positivity and
  maximum, expiry-after-issue, and schema-referenced length/charset rules. Verify: the bundle validates
  and every rule declares `rule_id`, `version`, `severity`, `gate_type`, `target_operations`.
- [x] 2.6 Every rule carries executable test vectors. Verify: test walks the bundle and executes each
  vector, asserting at least one `pass` **and one `finding` and one `needs_input`** outcome per rule
  (design D12 #3).

## 3. Coverage plan and report

- [x] 3.1 `app/audit/planner.py`: build the unit list from schema + bundle + context before any
  evaluation. Verify: test asserts unit ids are unique and deterministic, that every schema field yields
  its schema units, and that the plan is produced without evaluating anything.
- [x] 3.2 `app/audit/report.py::summarise()`: the only place that computes counts, `completion`,
  `outcome`, `freshness`, and the `no_applicable_checks` reason. Verify: conservation test
  (`sum(counts) == planned`), outcome matrix covering `pass+failed ≠ no_findings`, all-`not_applicable`
  → `unable_to_assess`, and `complete` only when every unit is pass/finding/not_applicable.
- [x] 3.3 Report carries its baseline. Verify: test asserts `verification.audit` holds snapshot digest,
  `schema_version`, bundle versions and `engine_version`, and that a differing digest marks the report
  stale rather than rebinding findings.

## 4. Findings and gate types

- [x] 4.1 Project units into `Issue` and rule failures into `Finding`, populating the four optional
  fields (`gate_type`, `target_operations`, `method`, `check_id`) and citing `rule_id` + version.
  Verify: test asserts a deterministic finding carries `gate_type` and a rule reference, and that
  severity never implies `blocking`.
- [x] 4.2 Model output can never hard-block. Verify: test feeding a `method="semantic"` finding with
  `gate_type="hard_block"` asserts the audit reports a contract violation and does not block on it.
- [x] 4.3 Anchors are checked, not guessed. Verify: test where a finding references an unknown field key
  yields a `failed` unit, and a resolvable key yields an anchor that points at that field.

## 5. Operation gate

- [x] 5.1 `app/audit/policy.py`: the per-operation policy table from design D8 as data. Verify: test
  asserts all six operations are covered and that `save_draft` has no content-based blockers.
- [x] 5.2 `app/audit/gate.py::evaluate(state, operation, candidate_digest)` →
  `{decision, operation, candidate_content_sha256, policy_revision, evaluated_at, reason_codes,
  authorized_finding_ids}`. Verify: matrix test over six operations × four states (clean,
  deterministic `hard_block`, `needs_input` on a required unit, missing bundle) asserting `allowed` only
  in the clean case and `blocked`/`indeterminate` for uncertainty.
- [x] 5.3 A decision binds the candidate. Verify: test asserting that a different candidate digest
  produces `indeterminate` (or `blocked`) and that client-supplied rule ids/statuses are ignored.
- [x] 5.4 The decision is stored on the run. Verify: test asserting `state["gate"]` holds the documented
  keys and is overwritten per evaluation, never merged with a previous decision.

## 6. Node and transport

- [x] 6.1 `app/nodes/audit.py`: call the pure functions, write one `StageReport`, return trail entries —
  no business logic in the node and no model call. Verify: node test asserting the stage report status,
  contract-valid trail ops, and that a failing audit still returns a report rather than raising.
- [x] 6.2 Register the `audit` stage target (after 0.2). Verify: `plan_standalone("audit", state)`
  returns a chain, and `POST /runs/{thread_id}/stages/audit` over `TestClient` returns the envelope.
- [x] 6.3 Expose `verification` and `gate` in the envelope. Verify: TestClient test asserting both keys
  are present after an audit and absent (or null) before it, and that adding them breaks no existing
  console-api test.

## 7. Human disposition

- [x] 7.1 Append-only disposition events for a run: `{finding_id, disposition, reason, actor, at}`, with
  `open` / `accepted` / `rejected` / `needs_human_review`. Verify: test asserting events append (earlier
  events unchanged), rejecting a `critical` finding without a reason is refused, and `accepted` does not
  alter the unit's state.

## 8. Evidence family retained

- [x] 8.1 Port the applicable evidence checks into `app/audit/evidence.py` as units with
  `method="deterministic"`: overreach ops in the trail, untraceable `extracted` values, dangling finding
  anchors. `provenance` normalises each document **once** via `normalized_full_texts()` (design D12 #1).
  Verify: tests for each, asserting `failed` units and the finding text naming the offending entry or field.
- [x] 8.2 Checks that cannot run on POC data (citation support, conflict, coverage declarations) are
  reported as `not_applicable` with a reason. Verify: test asserting they appear in the report as
  `not_applicable`, never silently skipped.
- [x] 8.3 Checker isolation. Verify: test where one check raises, asserting a `failed` item for that
  check, the remaining checks still run, and the run is not reported as having no findings.

## 9. Acceptance

- [x] 9.1 AT-01 determinism: audit the same snapshot twice and compare reports. Verify: pytest
  asserting equality apart from ids/timestamps, with no model provider configured.
- [x] 9.2 AT-02/AT-14/AT-15 outcomes: a clean fixture document; a document missing a required field; a
  document with only `inferred` values. Verify: pytest asserting `no_findings` / finding on the missing
  field / `needs_input` and the matching gate decisions for `start_approval`.
- [x] 9.3 AT-17 staleness: audit, then change the snapshot, then ask the gate. Verify: pytest asserting
  the gate refuses to `allow` on the stale report and asks for a re-audit.
- [x] 9.4 Write `openspec/changes/agent-audit/DEMO.md`: commands, bundle id/version/hash, engine version,
  the outcomes observed from 9.1–9.3, and an explicit statement that semantic checks (AUD-10) are not
  implemented. Verify: file exists and its numbers match the runs.

## Workflow follow-up

- Reconcile `agent-verify`'s `business-verification` delta with the ownership decision from 0.1 (trim its
  rule evaluation, keep bundle authoring) so two engines never ship.
- Wire `editor-shell`'s audit button to the `audit` stage target and relabel it (`Standardize fields` vs
  `Rule audit`) in that change, once 6.2 exists.
- Semantic checking (AUD-10) plus the machine reviewer is its own change; the report shape already
  carries `method`, so it is additive.
- Decide `openspec/config.yaml`'s `Language: zh` vs these English artifacts (affects all three owners).
- Archive with `/opsx-archive` once 9.1–9.4 pass and the boundary decision is merged.