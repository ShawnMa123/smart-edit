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
events, and template-driven audit (no template entity exists anywhere in the repo).

Template-specific constraints (verified):

| Fact | Consequence for the template design |
|---|---|
| `fields.yaml` is shared with `agent-normalize` and holds only the 15 guarantee fields — no `origin_country`-style fields | customer-specific fields cannot live in the field dictionary; they must come from the template and from `state["extra_fields"]` |
| `contains_clause` only supports `match_kind=exact_text` and applies to **a field's value**; there is no `clause_set` type | required/controlled clauses are document-level evidence, so they need their own unit family, not a DSL op |
| `find_conflicts()` already reports same-`rule_id`-two-versions and cross-bundle `gate_type` disagreement; `rule_conflict` blocks the gate | template/policy conflicts extend that machinery instead of inventing a second one |
| `Unit.family` is `Literal["schema","rule","evidence"]`; `summarise()` counts by status, not by family | adding a `template` family needs no change to the counting/conservation code |

Constraints: POC deadline with three people; no database; runs are process-scoped; no model provider,
so nothing semantic can be exercised.

## Goals / Non-Goals

**Goals:**

- One deterministic engine answering "does this snapshot satisfy the published rules", with every
  planned check accounted for.
- **Templates as data**: a customer's expectations (settlement currency, origin country, controlled
  clauses, lawful-source declaration) are a versioned pack the engine compiles onto its existing DSL and
  unit families — no customer rule may be hard-coded in Python, no customer field may be pushed into
  `fields.yaml`.
- A gate answering per protected operation that never allows on uncertainty.
- Fit the frozen contract with the smallest possible, purely optional additions.
- Runnable today as a stage target, with no database and no model.
- Recomputable: same snapshot + bundle + template + engine version ⇒ identical report.

**Non-Goals** (proposal's deferred list): the §10 HTTP surface, rule governance, async jobs/leases,
organisation permissions, semantic checks (AUD-10) — **including semantic clause equivalence, which this
build marks `unable_to_assess` with a reason code rather than judging** — variables (AUD-07), template
*authoring and governance* (a template editor, release/approval workflow), audit UI surfaces (AUD-23),
incremental audits (AUD-24), draft-export rules (AUD-15), applying suggested edits (AUD-17),
repeated-table row instances (`instance_id`).

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

### D12. Integrity and performance hardening (second pass)

Four items were tightened after review; none changes an externally visible decision, so they were applied
without a new sign-off round.

| # | Problem | Fix | Evidence |
|---|---|---|---|
| 1 | Locating spans re-normalised the whole document **per field** (and per candidate in `extract`) | `app/parsing/normalize.py::normalized_full_texts()`; `span_locatable(..., normalized=…)` and `extract.locate_span(..., normalized_blocks=…)` accept a pre-computed index. Both new parameters are optional, so existing callers keep working | provenance check on a 48.4k-character document with 15 fields: **314 ms → 19.9 ms** |
| 2 | `find_conflicts()` only caught the same `rule_id` at two versions | also reports the same `(field_id, category)` gated **inconsistently across bundles** (e.g. `hard_block` in `bank` vs `advisory` in `client`). A *single* bundle may legitimately carry both, so only cross-bundle disagreement counts | 2 new tests, including one asserting our own pack stays clean |
| 3 | Rule vectors only had to demonstrate `pass` | every rule must now produce `pass`, `finding` **and** `needs_input` | 4 vectors added; the gate test in `test_rule_bundles.py` enforces it |
| 4 | `audit_state(snapshot_digest="unknown")` defaulted silently | `snapshot_digest` is a **required** argument; a report that cannot name its snapshot can never be judged stale | `AuditRunError` + test |

*Why item 1 is in the shared layer:* `span_locatable` belongs to `app/parsing/normalize.py`, which Agent 4's
`provenance_check` also uses. The change is additive (optional keyword argument) and behaviour-preserving,
so it does not alter the seam; A applied it with the owner's approval.

### D13. Where the audit's rows land, and where the gate reads them

The frozen contract has no gate type on `Finding`, so the projection has to answer two questions at
once: what a client shows, and what the gate trusts.

| Output | Shape | Why |
|---|---|---|
| `verification.checks` | one `Issue` per **planned unit** (51 for a guarantee), `checker` = check id, `level` from the finding's severity or the unit status, `location` = the anchor | `Issue` is the only per-check row the contract offers; one row per unit is what makes "33 of 51 assessed" inspectable |
| the four optional `Issue` fields | `check_id`, `gate_type`, `target_operations`, `method` | a reviewer must see which row would block an operation without opening a second payload |
| `state["findings"]` | contract `Finding` rows, numbered by `app/findings.py` (`B-` prefix), `blocking` mirrors **only** `gate_type == "hard_block"` | severity never decides blocking (`agent-contract` §4.5, AUD-13) |
| `verification.audit["findings"]` | the audit's own copy: `id`, `check_id`, rule ref, `gate_type`, `target_operations`, `method`, anchor, evidence | the gate needs the gate type; the contract `Finding` deliberately does not carry one |

`gate.evaluate()` therefore reads `verification.audit["findings"]` and falls back to `state["findings"]`
only when no report exists. Reading the contract rows instead would silently treat every hard block as
`advisory` — the failure mode where the gate answers "allowed" and nobody notices.

`verdict` answers "can the audit stand behind this report", not "is the document good": `no_findings` →
`pass`, `findings_present` / `needs_input` → `warn`, `unable_to_assess` → `fail`. `credibility` is
`assessed / planned` with its formula spelled out; `score` stays `None` because a display number must
never feed a verdict (contract) — nothing computes one.

Transport consequences (tasks 6.2/6.3), all additive:

- `audit` is a stage target declaring the whole shared layer (`parse`, `extract`, `normalize`), because
  `execute_chain` runs a plan as written and never expands it transitively;
- `agent4` stays a **name**, not a second chain: `AGENT_TARGETS` maps it to `audit`, and an agent id
  without a registered target is still refused (409) rather than widened;
- a prerequisite stage this build does not implement (`merge`) is refused with a reason instead of being
  skipped — "run it anyway" would fabricate a stage that does not exist;
- the envelope always carries `verification` and `gate`; `null` means "no audit yet" / "the gate was
  never asked", never "clean";
- the node decides a gate **only** when the caller names an operation: an audit alone approves nothing.

### D14. Templates are a separate data pack, compiled onto the existing engine

`app/templates/<template_id>.yaml` sits beside the rule bundles but means something different: a bundle
is *executable expressions*, a template is *where the expectations come from* (field expectations,
clauses, internal declarations) plus the policy packs it belongs to. Templates never inline DSL
expressions — otherwise the template author has to speak the DSL, and template versioning gets tangled
with rule versioning.

```yaml
template_id: adidas-guarantee
version: 1.0.0
published: true
synthetic: true                  # demo pack; the report must say so
document_types: [guarantee]
counterparty: {name: Adidas AG, match: exact_normalized, field: beneficiary_name}
fields:
  - key: currency                # already in fields.yaml: expectation only
    allowed_values: [USD]        # "the settlement currency MUST be USD"
    gate_type: hard_block
  - key: origin_country          # not in fields.yaml → read from extra_fields
    type: country
    allowed_values: [VN, TH]     # "the origin country MUST be one of these"
    gate_type: hard_block
  - key: guarantee_amount
    required_when: {field_id: currency, equals: USD}
clauses:
  - clause_id: adidas-payment-clause
    requirement: required        # required | controlled | optional
    text: "Payment shall be made in USD within 30 days of presentation."
    gate_type: hard_block
  - clause_id: adidas-law-clause
    requirement: controlled
    text: "This guarantee is governed by the laws of England and Wales."
    gate_type: hard_block
internal_policy:
  - declaration_id: lawful-source
    text: "We confirm the funds are from lawful sources."
    waivable: true
    gate_type: human_review
policy_packs: [bank-core, adidas-customer]
```

*Why not put expectations in `fields.yaml`:* that dictionary is the shared input contract with
`agent-normalize` (and `agent-verify`); a customer's "must be USD" does not belong in the dictionary that
decides how to read a document. *Why not make the template a rule bundle:* AUD-08 requires the
required/controlled/optional classification to survive, and `contains_clause.exact_text` cannot express
"optional" or "semantic equivalence"; folding them into expressions would silently lose the category the
reviewer needs.

### D15. Field expectations compile to the existing DSL — no new operator

`allowed_values: [USD]` → `compare(currency, eq, literal string "USD")`; several allowed values →
`any(compare eq v1, compare eq v2 …)`; `required_when` → the rule's `applicability`, with the checked
field kept in `expression` only (D5's rule: a field being checked must never sit in `required_facts`).
The compiled rule is indistinguishable from a hand-written one, so `evaluate_rule()`,
`validate_against_schema()` and the vector gate apply unchanged.

*Alternative:* add an `allowed_values` op to `dsl.py` — shorter, but it puts a second comparison semantics
next to the typed `compare`, and needs its own three-valued rules and vectors. Compiling adds no semantic
surface.

### D16. Template fields merge into an effective schema and come from `extra_fields`

`effective_schema = SchemaBundle(fields.yaml) ∪ template-declared fields`; a type conflict on the same
`field_id` raises `TemplateError` at load time instead of degrading at run time. Template fields are read
from `state["extra_fields"]` (dictionary fields still come from `state["fields"]`), so neither
`fields.yaml` nor the frozen `app/state.py` changes, and `compare`'s type compatibility check keeps
working for them.

*Cost:* whether a template field can be judged depends on whether normalization extracted it into
`extra_fields`. Not-read stays `absent` (→ `needs_input` or a required finding); the health check lists
template fields so this is visible, never silently green.

### D17. Clause checks are a new unit family, not a DSL op

`contains_clause` acts on a field value and there is no `clause_set` type, while required/controlled
clauses are **document-level** evidence. So `app/audit/clauses.py` evaluates them over
`normalized_full_texts()` (the same normalization the provenance check uses):

| Template declaration | Result |
|---|---|
| `required`, text absent | `finding` (clause id + version cited) |
| `controlled`, text differs after fixed normalization | `finding`, never described as "equivalent" |
| `optional`, text absent | `not_applicable` |
| `semantic_equivalent` | `unable_to_assess` + `semantic_equivalence_not_implemented` — never `pass`, never a finding |

Only whitespace / full-half-width differences are normalized away; the original text stays in the report
for the reviewer.

### D18. Resolution: match, then refuse — never guess

Candidates = `published ∧ document_types ∋ business_type ∧ counterparty match`, where the counterparty
value comes from the field the template names (`counterparty.field`, default `beneficiary_name`) after
whitespace/full-width/case normalization.

| Candidates | Outcome |
|---|---|
| exactly 1 | use it; report `resolved_from = {document_type, counterparty_field, counterparty_value}` |
| 0 | every template unit `unable_to_assess`, reason `no_applicable_template` |
| ≥2 | `unable_to_assess`, reason `ambiguous_template`, report lists `{template_id, version}` pairs |

A host/UI reference may only **narrow** the candidate set; it cannot select an unpublished version and it
cannot override a version number. Client-supplied version declarations are ignored.

### D19. Policy combination adds a third conflict class

`ResolvedPolicy = base template + bank pack + customer pack + department pack`, each recording
`{pack_id, owner, version, valid_from, valid_to, source}`. Conflicts extend `find_conflicts()`:

1. same `rule_id` at two versions (exists today);
2. same `(field_id, category)` gated differently by different bundles (exists today);
3. **new**: a template expectation contradicting a policy pack's declaration (template says `hard_block`,
   customer pack says `advisory`), or a mandatory pack missing.

Any of the three: affected units → `unable_to_assess` with `policy_conflict` / `missing_policy_pack`, the
report gains `policy_conflict` in `reasons`, and the gate takes its existing `rule_conflict` path →
`blocked`. Load order never decides. Several rules for one field **inside** one pack remain legitimate
(there is already a test guarding that).

### D20. Report baseline: content digest and template digest stay separate

```json
"template": {
  "template_id": "adidas-guarantee",
  "version": "1.0.0",
  "content_sha256": "…",
  "synthetic": true,
  "counterparty": "Adidas AG",
  "document_types": ["guarantee"],
  "resolved_from": {"document_type": "guarantee", "counterparty_field": "beneficiary_name"},
  "policy_packs": [{"pack_id": "bank-core", "version": "1.0.0"}],
  "conflicts": [],
  "candidate_templates": []
}
```

`snapshot_digest` keeps hashing only "files + fields" — the template is not content of the candidate, so
mixing it in would let a template edit masquerade as a document edit. Template change is judged from
`template.content_sha256`: when the gate sees a report whose template digest no longer matches the
resolved template, it answers `stale_report` with reason `template_changed`. The baseline lives in
`verification.audit.template` (the optional key signed off in task 0.2), so `Issue` needs no new field
and `app/state.py` is untouched again.

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
- **[Template fields nobody extracts]** A template field such as `origin_country` is not in `fields.yaml`,
  so it arrives (or not) in `state["extra_fields"]`. If normalization never extracts it, the expectation
  is `absent` and reads like a document defect. → The loader reports template fields, `doctor` lists
  them, and the report keeps "not read" (`needs_input`) distinct from "genuinely missing" (`finding`).
- **[Ambiguous resolution freezes the audit]** Two templates for the same document type and counterparty
  make every template unit `unable_to_assess`. → The report lists the candidate `{template_id, version}`
  pairs, `doctor` warns, and a host reference may narrow the set (never to an unpublished version).
- **[Semantic equivalence quietly claimed]** The cheap version of AUD-08 is keyword matching dressed up as
  "equivalent". → `semantic_equivalent` is a distinct declaration that can only produce
  `unable_to_assess` + `semantic_equivalence_not_implemented`, and a test asserts it never returns `pass`.
- **[Template and bundle drift]** A bundle edit can invalidate a template's expectation (e.g. the field's
  type changes). → `validate_against_schema()` runs on compiled template rules too, so a template that no
  longer fits the schema is a load-time failure, and `doctor` reports both halves together.

## Migration Plan

Additive; nothing persisted yet, so no data migration.

1. **Sign-off gate**: boundary with `agent-verify` (**still open**, task 0.1) and the five optional
   contract fields + the `agent4` standalone flip (**approved by A on 2026-11-08**, tasks 0.2). The
   boundary question blocks nothing in code: `agent-verify` authors bundles, this change evaluates them.
2. `app/rules/` + `app/audit/` + `app/nodes/audit.py`, tested against plain dicts (no transport needed).
3. Register the `audit` stage target and expose it through the existing envelope.
4. **Templates**: loader + effective-schema merge + `doctor` first (no existing audit result changes), then
   the `template` unit family with `clauses.py`, then the report baseline and `template_changed`/
   `policy_conflict` in the gate. With no published template the plan is exactly today's 51 units, so the
   engine tests stay green throughout.
5. Rollback: delete the new modules and `app/templates/*.yaml`, and drop the `template` family from
   `build_plan()`; nothing else references them, and no frozen file gained a required field.

## Open Questions

1. **Boundary with `agent-verify`** — does B agree that `business-verification` becomes a bundle author
   (business parameters, requirement lists) while this group owns the engine and the gate? Blocking for
   code; recorded as task 0.
2. **Contract sign-off** — **answered for A (2026-11-08), B / C countersign pending.** A approved the
   five optional fields plus the standalone flip as a purely additive diff (`tasks.md` 0.2 records it),
   because nothing existing was renamed, removed or re-typed; the only behavioural change is that
   `agent4` becomes triggerable through the new `audit` target. B / C may still answer "no" — the
   rollback is deleting `app/nodes/audit.py`, `app/audit/project.py` and reverting those three small
   blocks.
3. **Artifact language** — `openspec/config.yaml` still declares `Language: zh` while these artifacts are
   English per an explicit instruction.
4. **Bundle authoring workflow** — POC bundles are hand-edited YAML reviewed in PR; AUD-20 governance is
   deferred, so the demo must say so.
5. **`assessment_date` source** — the audit needs a business date (§4.1); assume the run's ingest time
   unless the document supplies one. Recorded so nobody later "fixes" it by using today's date.
6. **Semantic checks** — deferred, but the report shape already carries `method`, so enabling AUD-10
   later is additive rather than a rewrite.
7. **Counterparty field** — which field identifies "the customer side" (`beneficiary_name` by default,
   `applicant_name` for bank-side templates). Each template declares `counterparty.field`, so the answer
   is a template edit, not a code change.
8. **Template body source** — this change keeps controlled-clause text inside the template YAML so the
   template can validate itself (`doctor`). In production the text should come from the host's template
   governance service (`EvidenceRef`); the loader is the single place that would change.