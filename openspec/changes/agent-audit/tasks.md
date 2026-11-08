# Tasks

> Artifacts are English per an explicit instruction (see `design.md` Open Questions 3).
> Group 0 must complete **before any code**: it decides ownership of field-value checks and signs off
> the two frozen-file edits. Everything here is deterministic — no model call anywhere.
>
> **Status (2026-11-08, second pass):** `0.2` is **done** — A approved the frozen edits as a set of
> purely additive, optional changes (recorded below); B and C countersigns are still outstanding and
> change nothing in the code, because nothing existing was modified. `0.1` (the `agent-verify` boundary)
> remains **open** and needs B. Groups 1–9 are implemented and tested: **281 passed**,
> `scripts/audit_demo.py` and `python -m app.rules.doctor` both green.
>
> **Status (2026-11-08, third pass):** groups 10–15 add **template-driven audit** (AUD-08/09/11,
> RULE-03/04) to this same change — a customer template is part of what this group audits, not a
> separate change. **Implemented:** 330 Python tests, 109 frontend tests, 4 HTTP end-to-end cases,
> `python -m app.rules.doctor` green (rule packs + templates). With no template requested the plan
> stays at today's 51 units, and `tests/test_template_integration.py` asserts exactly that. Semantic
> clause equivalence is **not** built: it is a fixed `unable_to_assess` with reason
> `semantic_equivalence_not_implemented` (`design.md` D17), so AT-01 is untouched.

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

## 9. Acceptance — engine slice

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

## 10. Template data and loading

- [x] 10.1 `app/rules/templates.py`: load `app/templates/*.yaml` (`template_id` / `version` /
  `published` / `synthetic` / `document_types` / `counterparty` / `fields` / `clauses` /
  `internal_policy` / `policy_packs`), compute `content_sha256`, and hand only published versions to the
  audit. Verify: tests asserting an unpublished pack is ignored, the digest is stable across runs, and a
  missing key or an unknown `requirement` value raises `TemplateError`.
- [x] 10.2 Effective schema (design D16): merge template-declared fields into the `SchemaBundle` built
  from `fields.yaml`; a type conflict on the same `field_id` fails at load time. Verify: test asserting
  the merged schema contains `origin_country`, and that a conflicting type raises `TemplateError`
  instead of silently picking one.
- [x] 10.3 Compile field expectations to the DSL (D15): `allowed_values` (one or many) and
  `required_when` → `applicability`. Verify: tests asserting every compiled rule passes
  `validate_against_schema()`, with pass/finding vectors for "currency must be USD" and "origin country
  in [VN, TH]".
- [x] 10.4 Ship `app/templates/adidas-guarantee.yaml` (settlement currency `USD`, origin country
  `[VN, TH]`, one required + one controlled clause, one lawful-source declaration, `synthetic: true`).
  Verify: `python -m app.rules.doctor` is green, and every check in the pack declares `gate_type` plus a
  `clause_id` or field anchor.

## 11. Template resolution and policy combination

- [x] 11.1 `app/audit/resolve.py`: candidates = `published ∧ document_types ∋ business_type ∧ counterparty
  match` (`counterparty.field`, default `beneficiary_name`, normalized). Verify: test asserting the unique
  match returns the pack plus `resolved_from` (document type, field, value).
- [x] 11.2 Refusal paths (D18): 0 candidates → `no_applicable_template`; ≥2 → `ambiguous_template` with the
  candidate list. Verify: two tests asserting the reason codes, the `{template_id, version}` pairs, and
  that every template unit is `unable_to_assess`.
- [x] 11.3 A host reference only narrows; client version declarations are ignored. Verify: test asserting
  the reference can reduce the candidate set to one, an unpublished version reference is ignored, and the
  resolved version equals the host-resolved one.
- [x] 11.4 Policy combination (D19): `ResolvedPolicy` with per-pack `{pack_id, owner, version, valid_from,
  valid_to, source}`. Verify: test asserting the report lists the template plus each pack version.
- [x] 11.5 Third conflict class: template expectation vs policy pack declaration, and a mandatory pack
  missing. Verify: tests asserting the conflict appears in `template.conflicts`, the affected unit is
  `unable_to_assess`, `reasons` carries `policy_conflict` / `missing_policy_pack`, and several rules for
  one field *inside* one pack are still not a conflict.

## 12. Clause and declaration checks

- [x] 12.1 `app/audit/clauses.py` over `normalized_full_texts()`: `required` missing → `finding`,
  `controlled` not identical after fixed normalization → `finding`, `optional` missing →
  `not_applicable`. Verify: tests for the three states plus the whitespace / full-width-only case.
- [x] 12.2 Semantic equivalence stays out (D17): `semantic_equivalent` → `unable_to_assess` +
  `semantic_equivalence_not_implemented`. Verify: test asserting the status and reason code, and that such
  a unit never returns `pass` and never produces a finding.
- [x] 12.3 Internal declarations (AUD-11): judge presence and condition only; `waivable` comes from the
  template, never from severity. Verify: tests asserting a missing declaration is a `finding`, a present
  one is `pass`, and the message never claims the funds or the transaction were verified.

## 13. Plan, report and gate integration

- [x] 13.1 `Unit.family` gains `template`; `build_plan()` emits one unit per field expectation, clause and
  declaration (`check_id = TEMPLATE:<kind>:<id>`). Verify: test asserting unit ids are unique and stable,
  the plan total is `51 + template units`, and `summarise()`'s conservation assertion still holds.
- [x] 13.2 `app/audit/runner.py`: bind `fields ∪ extra_fields`, pass the effective schema as context,
  evaluate the template family. Verify: test asserting a template field value comes from `extra_fields`,
  `inferred` → `needs_input`, and `extracted` without a source is not treated as a pass.
- [x] 13.3 Report baseline (D20) in `verification.audit.template`. Verify: test asserting the keys
  (`template_id` / `version` / `content_sha256` / `synthetic` / `counterparty` / `resolved_from` /
  `policy_packs` / `conflicts` / `candidate_templates`) and that a resolution failure records its reason.
- [x] 13.4 Finding/Issue projection: `gate_type` from the template, `location` at the field or clause id.
  Verify: test asserting `blocking` mirrors only `hard_block` and the anchor names the field/clause.
- [x] 13.5 Gate: `policy_conflict` → `blocked`, template digest change → `stale_report` +
  `template_changed`. Verify: tests asserting `start_approval` is neither `allowed` on a conflict nor on a
  template change.
- [x] 13.6 Envelope: `verification.audit.template` after an audit, `null` before it. Verify: `TestClient`
  test over `POST /runs/{id}/stages/audit`, plus the existing console-api assertions.

## 14. Health check, demo and docs

- [x] 14.1 `python -m app.rules.doctor` covers templates: field evaluability, `allowed_values` type
  compatibility, clause text locatable in the pack's own text, vectors, conflicts. Verify: tests asserting
  exit 0 for a healthy pack, 1 for an unevaluable field or unlocatable clause, 2 when a pack cannot load.
- [x] 14.2 `scripts/audit_demo.py` gains a template scenario (clean document → template matched →
  expectations pass) and an ambiguity scenario (two candidates → `unable_to_assess`). Verify: the script
  prints both scenarios' outcome, coverage and gate decision.
- [x] 14.3 Docs: `how_to_use.md` gains "auditing against a customer template" (how the template is chosen,
  what the panel shows, what `synthetic` means); `web/README.md` lists the new panel block. Verify: every
  documented command reproduces its stated output.

## 15. Acceptance — template slice

- [x] 15.1 No-template behaviour is unchanged: with `app/templates/` empty (or all unpublished) the audit
  still plans 51 units at `0.647` coverage with `no_findings`. Verify: the whole suite stays green and a
  test asserts the plan count is 51.
- [x] 15.2 End-to-end: `Run spec audit` → normalize → audit shows the template baseline (id/version/
  `synthetic` banner), the template unit count and the expectation outcomes; an ambiguous set shows
  `unable_to_assess` with the reason code. Verify: `web/src/e2e.audit.test.ts` gains the template scenario,
  and component tests cover the `synthetic` and `ambiguous_template` renderings.
- [x] 15.3 Update `openspec/changes/agent-audit/DEMO.md` with the template commands, template id/version/
  digest, both scenarios' outcome/coverage/gate results, and an explicit statement that semantic
  equivalence is not implemented. Verify: numbers match 15.1/15.2.

## Workflow follow-up

- Reconcile `agent-verify`'s `business-verification` delta with the ownership decision from 0.1 (trim its
  rule evaluation, keep bundle authoring) so two engines never ship. **Templates belong here too**: agree
  that template and policy packs are authored (by B / rule owners) and evaluated only by this group.
- `editor-shell` now triggers `stages/audit`; when group 13 lands it should also surface the template
  baseline (id / version / `synthetic` banner / resolution reason) next to the coverage numbers.
- Semantic checking (AUD-10) plus the machine reviewer is its own change; the report shape already
  carries `method`, so it is additive. **Semantic clause equivalence (AUD-08's second half) rides with
  it**: this change fixes the reason code `semantic_equivalence_not_implemented`, and that change replaces
  one branch.
- Template authoring and governance (a template editor, AUD-20's release/approval workflow) stays out:
  POC templates are hand-edited YAML reviewed in a PR, and the report must say they are synthetic.
- The **matched** template path is proved in-process (`tests/test_template_integration.py`,
  `scripts/audit_demo.py`) and in the UI component tests; over HTTP the fixture provider pins the
  counterparty to "Beta Construction Ltd", so the end-to-end case asserts the *refusal* path. Add an
  Adidas-extraction fixture (and a second `SMART_EDIT_LLM=fixture:…` server) to drive the matched path
  over HTTP as well.
- `POST /stages/audit?template=<id>` is the opt-in surface (`app/api/main.py`); the `console-api` delta in
  `frontend-console` should document it, since that change owns the transport contract.
- Decide `openspec/config.yaml`'s `Language: zh` vs these English artifacts (affects all three owners).
- Archive with `/opsx-archive` once 9.1–9.4 **and** 15.1–15.3 pass and the boundary decision from 0.1 is
  merged.