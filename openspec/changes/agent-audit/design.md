# Design

## Context

Sources: `tradeAI_requirementDesign_v2/AI-audit_reqirement.md` (AUD-01…24, AT-01…30, §4 snapshot /
schema / coverage plan, §5 closed DSL and three-valued logic, §7 states / severity / gate, §10 API)
and `Requirements.md` §9.1–§9.3 (RULE-01…04). See `proposal.md` for why the identity moves.

What the repo actually gives us (verified):

| Exists | Shape that constrains the design |
|---|---|
| `app/state.py` (frozen) | `FieldValue.status ∈ {extracted, inferred, missing}`, `Finding`, `StageReport`, `VerificationReport{checks: Issue[], verdict, credibility, score}`, `Issue{checker, level, finding_ids, detail, location}`, `EditState.gate: dict \| None` |
| `app/configs/fields.yaml` | 15 fields with `type`, `required`, `stage.normalize=[max_length, charset, precision, thousands, date_order]` — already a usable schema |
| `app/stages.py` | `STAGE_TARGETS` = parse/extract/normalize only; `AGENT_SPECS["agent4"].standalone is False` |
| `app/runtime.py` | `execute_chain()` drives stage nodes; `merge_update()` owns reducer semantics |
| `app/verifier/` | **does not exist** — `agent-audit` was never implemented (0 tasks) |

Gaps to fill: rule engine, rule bundles, coverage accounting, `gate_type`, gate evaluator, disposition
events.

Constraints: POC deadline with three people; no database; runs are process-scoped; no model provider,
so nothing semantic can be exercised.

## Goals / Non-Goals

**Goals:**

- One deterministic engine answering "does this snapshot satisfy the published rules", with every
  planned check accounted for.
- A gate answering per protected operation that never allows on uncertainty.
- Fit the frozen contract with the smallest possible, purely optional additions.
- Runnable today as a stage target, with no database and no model.
- Recomputable: same snapshot + bundle + engine version ⇒ identical report.

**Non-Goals** (proposal's deferred list): the §10 HTTP surface, rule governance, async jobs/leases,
organisation permissions, semantic checks (AUD-10), variables (AUD-07), template and policy bundles
(AUD-08/09/11), audit UI surfaces (AUD-23), incremental audits (AUD-24), draft-export rules (AUD-15),
applying suggested edits (AUD-17).

## Decisions

### D1. The group audits documents; the evidence family stays as an internal guard

`rule-audit` is the group's identity: snapshot + versioned rules + coverage + gate. The seven
evidence-chain checks keep their definitions but move from "the product" to "a check family verifying
the audit's own inputs" — same report, units with `method = deterministic`.

*Why:* the two answer different questions ("does the document satisfy the rules" vs "can we trust the
values we read"). Merging them into one unlabelled verdict is how a data-quality problem gets reported
as a compliance problem. *Alternatives:* keep `output-verification` as the identity and bolt rule checks
beside it — rejected: RULE-01…04 would still have no owner, which is the defect this change fixes.

### D2. POC slice on the existing field model, everything else deferred by AUD id

In scope: AUD-02 (four states), AUD-03 (schema types), AUD-04 (amount), AUD-05 (date), AUD-06
(charset/length), AUD-12 (coverage), AUD-13 (finding shape), AUD-14 (gate), AUD-16 (disposition), the
evidence family, and recomputability (AT-01).

*Why:* those are decidable from data the repo already produces. AUD-07/08/09/10/11/15/17/18/19/20/21/
22/24 need inputs that do not exist yet (no variables, no templates, no model, no permissions, no DB).
*Alternatives:* plan all 24 and ship none; or fake semantic checks with the fixture model, which would
forfeit AT-01.

### D3. Map the report model onto the frozen types; add only optional fields

| AI-audit concept | Lands in |
|---|---|
| `AuditReport` (outcome, completion, freshness, coverage, counts, engine/bundle versions) | `VerificationReport.audit` — **new optional dict** |
| `CheckResult` (one planned unit) | one `Issue` (`checker` = check id, `level`, `detail`) |
| `Finding` (category, gate_type, anchors, rule ref, disposition) | existing `Finding` + four optional fields |
| `GateDecision` | `EditState.gate` (already `dict \| None`) |
| `FindingDisposition` events | in-memory append-only list on the run |

Contract additions, all `NotRequired`: `Issue.gate_type`, `Issue.target_operations`, `Issue.check_id`,
`Issue.method`, `VerificationReport.audit`.

*Why:* `app/state.py` is frozen with "子结构只增不改；新增字段必须可选", and the gate node already reads
`verification`; a parallel DTO tree would need adapters everywhere. *Alternatives:* new
`AuditReport`/`CheckResult` TypedDicts (cleaner names, but a second verdict vocabulary for one run and a
bigger sign-off).

### D4. Rules are versioned YAML bundles in a closed DSL; `fields.yaml` is the schema bundle

`app/rules/bundles/*.yaml`, each with `bundle_id`, `version`, `published`, `content_sha256`, and rules
built from `all` / `any` / `not` / `exists` / `compare` / `length` / `charset` / `contains_clause`.
No scripts, no user regex, no network, no model. Schema checks are generated from `fields.yaml` and are
always on; business rules live in a `guarantee` bundle.

*Why:* a closed op set is what makes AT-01 (identical results) and AT-27 (no executable code)
achievable, and YAML lets a rule owner edit rules without shipping Python. *Alternatives:* Python
predicate functions (fast to write, impossible to govern or hash); JSON Schema alone (cannot express
cross-field rules such as expiry-after-issue).

### D5. Three-valued evaluation, applicability first, required fields never pre-swallowed

Order: schema binding → context availability → applicability → expression. Applicability `false` ⇒
`not_applicable`; `unknown` ⇒ `needs_input` / `unable_to_assess`; expression `unknown` is never `pass`.
A rule's `required_facts` may hold document type or assessment date, **not** the field the rule checks.

*Why:* `AI-audit §5.1` calls this out — putting `amount` into `required_facts` means a missing amount
can never produce a finding, silently converting the most important defect into a skipped check.
*Alternatives:* two-valued evaluation with defaults (turns "unknown" into pass or fail; both wrong).

### D6. Coverage is planned, then executed, then summarised by one function

`app/audit/planner.py` builds the unit list before any evaluation;
`app/audit/report.py::summarise()` is the only place counts, `completion`, `outcome` and `freshness`
are computed, and it asserts `sum(counts) == planned`.

*Why:* every "we showed a clean result" bug starts with counting what ran instead of what was planned.
One function with a conservation assert is the cheapest defence. *Alternatives:* counts computed per
check family (drift, and no single place to assert).

### D7. Value binding: `extracted` counts as machine-confirmed, `inferred` does not

| `FieldValue` state | Audit view |
|---|---|
| `status="missing"`, `value=None` | **absent** ⇒ rule finding (AUD-02) |
| `status="extracted"` with `source` | **confirmed** ⇒ evaluate normally |
| `status="inferred"` (or `confirmed=false`) | **unconfirmed** ⇒ `needs_input`, never `pass` |
| `status="extracted"` but `source is None`, or span not locatable | **contract violation** ⇒ `failed` unit |

*Why:* `agent-contract` says an `extracted` value is locatable in its own file and "MAY 免人工核对",
while `inferred` must be confirmed by a human at HITL. Treating every `confirmed=false` value as
unconfirmed would make every pre-HITL audit `needs_input` and the gate permanently blocked — and would
train reviewers to ignore the state. *Alternatives:* require `confirmed` for everything (gate never
opens before HITL); treat `inferred` as confirmed (silently promotes guesses to facts).

### D8. Gate policy per operation, and only deterministic rules can hard-block

| Operation | Blocked by | Notes |
|---|---|---|
| `save_draft` | nothing content-related | identity/lock still apply (AUD-14) |
| `submit_version` | deterministic `hard_block` findings | gaps are listed, not hidden |
| `start_approval` | `hard_block`, any `needs_input` on a required unit, unresolved critical disposition | |
| `formal_export` | same as approval, and the decision binds the candidate digest | |
| `handoff` | approval-level checks + an approved version exists | |
| `formal_mapping` | returns `indeterminate` — no message-type bundle in this build | |

*Why:* §7.2 makes severity independent of blocking: a `critical` warning is not by itself a stop, and a
model opinion is never a stop. Encoding this as data (`app/audit/policy.py`) keeps it reviewable.
*Alternatives:* one global "any critical ⇒ block" rule (over-blocks drafts, under-blocks approvals).

### D9. Disposition is append-only, in memory, per run

Events shaped `{finding_id, disposition, reason, actor, at}` keyed by run; rejecting a `critical`
finding requires a `reason`.

*Why:* no database this phase, and rewriting a disposition would break the audit trail the group exists
for. *Alternatives:* a mutable status field (loses history, breaks AT-18); a DB table (out of scope).

### D10. Engine purity is enforced by a test, not by documentation

`tests/test_rule_engine.py` asserts the engine module tree imports neither `app.llm` nor an HTTP client,
and a determinism test audits the same snapshot twice and compares reports byte-for-byte (minus ids and
timestamps).

*Why:* the most likely future "improvement" is asking a model to handle a rule it cannot express, which
would silently destroy AT-01. A test is the only thing that survives a deadline.
*Alternatives:* a comment in the module docstring.

### D11. Coverage thresholds and decision transparency (adopted default)

The report carries `coverage = {assessed, not_applicable, unsettled, ratio}` where
`assessed = pass + finding` — **`not_applicable` never counts as assessed**. The gate applies three rules,
but only to operations that assert "this document is ready" (`start_approval`, `formal_export`, `handoff`,
`formal_mapping`):

| Rule | Condition | Decision |
|---|---|---|
| R1 | `assessed == 0` | `indeterminate`, reason `no_assessed_checks` |
| R2 | `ratio < 0.30` | `indeterminate`, reason `limited_coverage` |
| R3 | `0.30 ≤ ratio < 0.60` | `allowed` **with** reason `limited_coverage`, so the client must print "assessed X of Y planned" |

`save_draft` and `submit_version` are exempt (`enforce_coverage=False`): `REVIEW.md` decision 2 deliberately
allows a discussion version to carry gaps, and gating it on coverage would contradict that decision.

Every decision also carries `coverage`, `open_gaps`, `advisory_finding_ids` and `unsupported_capability`, so
an `allowed` answer states what it is allowing instead of being a bare verdict — which is the failure mode
Decision 2 warned about.

*Why thresholds rather than UI text alone:* the third measured sample has **1 of 51** units assessed and the
report merely says `needs_input`; a screen can be ignored, a decision cannot.
*Adopted by A on 2026-11-08 as the default while `REVIEW.md` decision 1 is out for countersign.* The values
are two constants in `app/audit/policy.py` (`MIN_ASSESSED_RATIO`, `LIMITED_COVERAGE_RATIO`); answering
differently changes a constant and one test, not a design.

## Risks / Trade-offs

- **[Two engines for one document]** `agent-verify` also claims field-value legality ⇒ split ownership
  and contradictory findings on the same snapshot. → The boundary decision is task 0, before any code:
  `agent-verify` authors bundles, this group evaluates and gates.
- **[Contract sign-off stalls the work]** The five optional fields and the standalone flip touch frozen
  files. → They are collected in one sign-off checklist with rationale; engine and planner are built and
  tested against plain dicts in the meantime.
- **[Coverage conservation erodes under deadline pressure]** → `summarise()` is the only counter and it
  asserts; the conservation test ships with the planner, not at the end.
- **[Everything `not_applicable`]** A document type with no bundle yields `unable_to_assess`, which a
  demo audience can misread as "fine". → The report (and any UI) must render reason
  `no_applicable_checks` explicitly.
- **[Deterministic-only looks weaker than "AI audit"]** → By design: the report states semantic checks
  (AUD-10) are not implemented, instead of shipping a model opinion labelled as a rule.
- **[`fields.yaml` is both runtime config and schema]** A schema edit silently changes audit results. →
  The bundle records the schema version (hash of `fields.yaml` at load) and reports include it.
- **[Anchor drift]** Findings hold field keys, not character offsets; if a value moves the anchor still
  resolves. → Accepted for the POC; richer anchors are AUD-13's deferred half.

## Migration Plan

Additive; nothing persisted yet, so no data migration.

1. **Sign-off gate**: boundary with `agent-verify`, the five optional contract fields, the `agent4`
   standalone flip. Nothing else starts until this is recorded.
2. `app/rules/` + `app/audit/` + `app/nodes/audit.py`, tested against plain dicts (no transport needed).
3. Register the `audit` stage target and expose it through the existing envelope.
4. Rollback: delete the new modules and revert the two frozen-file edits; nothing else references them.

## Open Questions

1. **Boundary with `agent-verify`** — does B agree that `business-verification` becomes a bundle author
   (business parameters, requirement lists) while this group owns the engine and the gate? Blocking for
   code; recorded as task 0.
2. **Contract sign-off** — five optional fields plus one standalone flip, three-person approval.
3. **Artifact language** — `openspec/config.yaml` still declares `Language: zh` while these artifacts are
   English per an explicit instruction.
4. **Bundle authoring workflow** — POC bundles are hand-edited YAML reviewed in PR; AUD-20 governance is
   deferred, so the demo must say so.
5. **`assessment_date` source** — the audit needs a business date (§4.1); assume the run's ingest time
   unless the document supplies one. Recorded so nobody later "fixes" it by using today's date.
6. **Semantic checks** — deferred, but the report shape already carries `method`, so enabling AUD-10
   later is additive rather than a rewrite.