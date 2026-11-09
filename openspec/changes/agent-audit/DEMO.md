# Demo record — standards audit group (`agent-audit`)

Evidence for tasks 9.1–9.4. Artifacts are English per an explicit instruction
(`design.md` Open Questions 3).

## Environment observed

| Item | Value |
|---|---|
| Engine version | `1.0.0` |
| Policy revision | `2026-11-08.2` (coverage thresholds + decision transparency) |
| Schema version (hash of `app/configs/fields.yaml` projection) | `044a959e73af` (15 fields) |
| Rule bundle | `guarantee-core` v`1.0.0`, content hash `0c57550bb485` |
| Planned check units for a guarantee document | **51** (schema units + 6 rules + 6 evidence checks) |
| Model calls during an audit | **0** |

```bash
.venv/bin/python scripts/audit_demo.py            # one command: plan, coverage, outcome, gate decisions
.venv/bin/python scripts/audit_demo.py --json      # same payload as JSON (evidence for this file)

.venv/bin/python -m app.rules.doctor              # rule-pack health check (exit 0 healthy / 1 problems / 2 unloadable)
.venv/bin/python -m app.rules.doctor --json       # same report as JSON, for CI

.venv/bin/python -m pytest tests/test_rule_schema.py tests/test_audit_bind.py \
    tests/test_rule_dsl.py tests/test_rule_engine.py tests/test_rule_bundles.py \
    tests/test_rule_doctor.py tests/test_audit_planner.py tests/test_audit_report.py \
    tests/test_audit_gate.py tests/test_audit_disposition.py tests/test_audit_evidence.py \
    tests/test_audit_acceptance.py tests/test_audit_perf.py -q
```

## 9.1 Determinism (AT-01)

Auditing the same snapshot twice with the same bundle and engine produces an identical report and
identical per-unit statuses — asserted by `test_at01_determinism`. Because the engine has no model and
no I/O, this is a property of the code, not luck.

## 9.2 Outcomes and gate decisions

| Document | Outcome | completion | Gate `start_approval` | Gate `submit_version` |
|---|---|---|---|---|
| Clean guarantee (8 fields extracted, spans locatable) | `no_findings` | `complete` | **allowed** | allowed |
| `guarantee_amount` absent | `findings_present` (finding `SCHEMA:guarantee_amount:required`) | `partial` | **blocked** (`hard_block`) | allowed |
| Every value `inferred` (unconfirmed) | `needs_input` (31 units) | `partial` | **blocked** (`needs_input`) | allowed (`gaps_listed`) |

Note the third row: an unconfirmed document may be **submitted as a version** with its gaps listed, but
may not **start approval** — the policy table (§7.2), not the severity, decides.

### Coverage and decision transparency (adopted default, `design.md` D11)

The report also carries `coverage = {assessed, not_applicable, unsettled, ratio}` (measured: 0.647 / 0.529 /
0.020 for the three samples). The gate applies R1 (`assessed == 0` → `indeterminate`), R2 (`ratio < 0.30` →
`indeterminate`) and R3 (`0.30–0.60` → `allowed` **with** `limited_coverage`) to `start_approval` /
`formal_export` / `handoff` / `formal_mapping` only. `save_draft` and `submit_version` are exempt so a
discussion version may carry gaps (`REVIEW.md` decision 2).

Every decision now also reports `coverage`, `open_gaps`, `advisory_finding_ids` and
`unsupported_capability`, so an `allowed` answer states what it is allowing.

### Hardening added after review

| Change | Where |
|---|---|
| Rules are validated against the schema at load time (unknown field ids, incomparable literal types) instead of degrading silently at run time | `app/rules/bundles.py::validate_against_schema`, called from `app/audit/runner.py` |
| `value_unparsable` (document defect) separated from `rule_type_mismatch` (rule defect, yields `failed`) | `app/rules/engine.py` |
| Comparison requires **exact** types — `datetime` subclasses `date`, so a date field vs a datetime literal is now a rule error rather than a crash | `app/rules/engine.py::_comparable` |
| Unreachable `(bool, bool)` comparison branch removed (no boolean field type exists) | `app/rules/engine.py` |
| `integer` vs `decimal` was allowed by the loader but failed at run time | numeric promotion in `_comparable`/`_compare` (`app/rules/engine.py`) |
| Span location re-normalised the whole document per field: **314 ms → 19.9 ms** on a 48.4k-character, 15-field document | `normalized_full_texts()` + optional `normalized` / `normalized_blocks` parameters (design D12 #1) |
| Cross-bundle `gate_type` disagreement is now reported as a conflict | `app/rules/bundles.py::find_conflicts` (design D12 #2) |
| Rule vectors must demonstrate `pass` + `finding` + `needs_input` | `app/rules/bundles/guarantee.yaml` + `tests/test_rule_bundles.py` (design D12 #3) |
| `snapshot_digest` is a required argument | `app/audit/runner.py` (design D12 #4) |
| An impossible date (`2026-02-30`) is a finding with `reason=invalid_value` — the calendar is real, not just a format check | `app/rules/engine.py::evaluate_schema_check` + `tests/test_rule_engine.py` |
| A working-day / holiday rule cannot be authored at all: the closed op set refuses it at load time instead of guessing a business day | `app/rules/dsl.py` + `tests/test_rule_engine.py` |

### Rule-pack doctor (`OPTIMIZATION.md` P3 item 4)

`python -m app.rules.doctor` answers the four questions a rule owner has before publishing, and its
**exit code** is the gate: `0` healthy, `1` problems found, `2` the packs could not be loaded at all
(so "checked nothing" can never read as "all good"). Observed on the shipped pack:

```
Rule-pack doctor · engine 1.0.0
  schema 044a959e73af (15 fields)
  bundle guarantee-core v1.0.0 published=True rules=6 sha256=0c57550bb485
  plan: 51 units (schema 39 · rules 6 · evidence 6)
  vectors:
    GR-AMOUNT-POSITIVE           v1   3 vectors -> finding, needs_input, pass
    ...
OK: no problems found                 # exit 0
```

It refuses a pack whose vector disagrees with the engine (`expected pass, got finding`), a rule with no
vectors, a rule referencing a field the schema does not define, and two published sources contradicting
each other — each asserted in `tests/test_rule_doctor.py`.

Test suite after this work: **281 passed** (including the performance guard in `tests/test_audit_perf.py`).

## 9.3 Staleness (AT-17)

```
gate start_approval on a report audited for digest-clean, asked about digest-after-edit
  -> indeterminate, reason_codes ['stale_report']
```

And `mark_stale()` keeps the report readable: it records `freshness=stale`,
`freshness_reasons=['snapshot_changed']`, and still names the snapshot it audited
(`snapshot_digest=digest-clean`). Findings are never re-pointed at newer text.

## Audit over the console transport (tasks 3.3, 4.x, 6.1-6.3)

The engine was reachable only from Python until task 0.2 was approved; it is now a stage target.

```bash
# after `uvicorn app.api.main:app` with SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json
curl -s -X POST "localhost:8000/runs/$TID/stages/audit" | python3 -m json.tool | head -40
```

Observed on the bundled fixture document (`fixtures/llm/sample_document.txt`):

```
stages      : [('parse','done',0), ('extract','done',1), ('normalize','done',0), ('audit','done',0)]
supported   : ['audit', 'extract', 'normalize', 'parse']
issues      : 51   verdict: pass   score: None
credibility : {assessed: 33, planned: 51, ratio: 0.647}
audit       : planned 51 outcome no_findings snapshot_digest 024696a7c5c2…
findings    : []   | gate: None
```

What that one call now produces:

| Surface | Observed |
|---|---|
| `stages` | `parse`, `extract`, `normalize`, `audit`; the audit report is `agent4`, `status=done`, `model_calls=0` |
| `verification.checks` | **51 `Issue` rows** — one per planned unit, each with `check_id`, `level`, `location` (the anchor), `method`, and `gate_type` + `target_operations` when it gates something |
| `verification.verdict` | `pass` on a clean document, `warn` when findings or gaps exist, `fail` when the audit cannot vouch (`unable_to_assess`) |
| `verification.credibility` | `{assessed: 33, planned: 51, ratio: 0.647, formula: "assessed / planned, assessed = pass + finding (not_applicable never counts)"}` |
| `verification.score` | `null` — always. A display number must never feed a verdict, so nothing computes one |
| `verification.audit` | the report baseline: `snapshot_digest`, `schema_version`, `bundle_versions`, `engine_version`, `counts`, `coverage`, `outcome`, `findings` |
| `findings` | contract `Finding` rows numbered `B-001…`; `blocking` mirrors **only** `gate_type == "hard_block"` |
| `gate` | `null` after an audit — the audit alone approves nothing; a decision appears only when an operation is asked for |

### Where the gate reads its findings (design D13)

The contract `Finding` carries no gate type, so the audit keeps its own copy at
`verification.audit["findings"]` and `gate.evaluate()` reads *that*. Reading `state["findings"]` instead
would silently downgrade every hard block to `advisory` — the gate would answer `allowed` and nobody
would notice. `tests/test_audit_node.py::test_the_stored_report_is_what_the_gate_reads` asserts the
difference: the same run is `blocked` through the report and would not have been through the contract
rows.

Two contract guards run on every audit, so a producer cannot opt out:

| Guard | Behaviour |
|---|---|
| `enforce_method_contract()` (4.2) | a `method="semantic"` finding with `gate_type="hard_block"` becomes a `failed` unit with reason `semantic_hard_block`; the finding is dropped, so it can never block |
| `enforce_anchor()` (4.3) | a finding whose anchor is not a schema field and not a normalized field becomes a `failed` unit with reason `dangling_anchor` — the anchor is never guessed |

### Transport refusals that did not exist before

| Request | Answer |
|---|---|
| `POST /stages/agent4` | runs the audit (`AGENT_TARGETS` maps the agent id to its one registered target) |
| `POST /stages/audit` on a run that never normalized | backfills `parse → extract → normalize`, then audits |
| `POST /stages/agent2` | `409 unknown_stage` — agent2 has no registered target |
| a registered target requiring a stage this build does not implement | `409 REFUSED` naming the missing stage, instead of running without it |

`REVIEW.zh-CN.md` decisions 1–3 still shape what the gate answers; the audit does not decide them.

## Templates (groups 10-15, AUD-08/09/11)

A customer template is part of what this group audits, not a separate change. Template-driven audit is
**opt-in per run**: without a request the audit still plans exactly the 51-unit baseline.

```bash
.venv/bin/python -m app.rules.doctor        # rule packs **and** templates
.venv/bin/python scripts/audit_demo.py      # [template matched] and [two templates match]

# over HTTP — `?template=` may only narrow which published pack applies
curl -s -X POST "localhost:8000/runs/$TID/stages/audit?template=adidas-guarantee" | python3 -m json.tool
```

| Item | Value |
|---|---|
| Template | `adidas-guarantee` v`1.0.0`, content hash `1e8077f8ce1c`, `synthetic: true` |
| Its expectations | `currency ∈ [USD]` (advisory — the bank pack already gates it), `origin_country ∈ [VN, TH]` (hard block), `guarantee_amount` required when currency is USD |
| Its clauses | 1 required + 1 controlled (both locatable in the pack's own `body`), 1 `lawful-source` declaration |

### Measured outcomes

| Scenario | Planned | Template units | Outcome | Gate `start_approval` |
|---|---|---|---|---|
| Template matched (Adidas counterparty, expectations satisfied) | **58** | 6 | `no_findings`, coverage **0.69** | — (not asked in the demo) |
| Same document, two packs match | 52 | 1 (`TEMPLATE:resolution`) | `unable_to_assess` (`ambiguous_template`), candidates listed | `indeterminate` |
| No template requested | **51** | 0 | `no_findings`, coverage 0.647 | unchanged |

Plan arithmetic for a matched run: 39 base schema units + `origin_country`'s type unit + 6 rule units +
6 evidence units + 6 template units (3 field expectations + 2 clauses + 1 declaration) = **58**.

### What the template layer refuses to do

- **Semantic clause equivalence is not implemented.** `requirement: semantic_equivalent` is
  `unable_to_assess` with reason `semantic_equivalence_not_implemented` — never a keyword match, never
  `pass`, never a finding. AUD-10 and this half of AUD-08 belong to a later change; AT-01 is untouched
  because no model enters the audit path.
- **A missing/ambiguous template is never resolved by guesswork.** Zero matches → `no_applicable_template`;
  several → `ambiguous_template` with `{template_id, version}` candidates; a client reference can only
  narrow, and an unpublished or unknown id is ignored (recorded as `reference_ignored`).
- **A template edit invalidates a report.** `verification.audit.template.content_sha256` is compared by the
  gate: a mismatch answers `stale_report` with reason `template_changed`. `snapshot_digest` stays
  content-only, so a template edit can never masquerade as a document edit.
- **Template fields are read from `extra_fields`.** `origin_country` is not in `fields.yaml`; when
  normalization does not extract it the unit is `needs_input` ("not read"), not a missing-value finding.
- **Policy conflicts stay visible.** A pack that gates a field *only* differently from the template (or a
  mandatory pack that is missing) puts the conflict in `template.conflicts`, makes the affected unit
  `unable_to_assess`, adds `policy_conflict` / `missing_policy_pack` to the report reasons, and blocks the
  gate. Load order never decides.

### Health check

`python -m app.rules.doctor` now covers templates and keeps the same exit-code contract (`0`/`1`/`2`):

```
template adidas-guarantee v1.0.0 published=True synthetic=True sha256=1e8077f8ce1c
         fields=3 clauses=2 declarations=1 plan=58 conflicts=0
  field currency        -> finding, needs_input, pass
  field origin_country  -> finding, needs_input, pass
  field guarantee_amount -> finding, needs_input, pass
```

Each expectation must demonstrate `pass`, `finding` **and** `needs_input` — the same bar the rule vectors
meet — so a template that can only ever pass fails the check.

### Tests

`330` Python tests and `109` frontend tests (plus 4 HTTP end-to-end cases) cover the slice; the
no-template path is asserted to stay at exactly 51 units / 0.647 coverage.

## What this build deliberately does **not** do

- **Semantic checks (AUD-10) are not implemented.** There is no model in the audit path, so no
  `method="semantic"` finding can be produced by this build. The report shape carries `method` so
  enabling it later is additive, not a rewrite. **The same holds for AUD-08's semantic clause
  equivalence**: a `semantic_equivalent` clause declaration is reported as `unable_to_assess` with reason
  `semantic_equivalence_not_implemented`, never as a match decided by keywords.
- **Templates are in this change's scope (tasks 10–15) but not built yet.** Until groups 10–15 land there
  is no template entity, so every audit runs on the published rule bundle alone (51 units). When they
  land, the report gains `verification.audit.template` and the gate learns `policy_conflict` /
  `template_changed`.
- Variables (AUD-07), draft-export rules (AUD-15), applying suggested edits (AUD-17), organisation
  permissions (AUD-18/19), rule governance and the management API (AUD-20/§11), template *authoring*
  (a template editor / release workflow), async jobs, leases and fencing (AUD-21), retention (AUD-22),
  audit UI surfaces (AUD-23), incremental audits (AUD-24), and the `/audit/*` HTTP surface (§10).
- Evidence checks that need other agents' outputs (citation support, conclusion conflict, coverage
  declaration) report `not_applicable` with reason `requires_agent_regulatory_output` — they are never
  silently skipped.

## Blocked tasks and what unblocks them

| Task | Blocked by |
|---|---|
| `0.1` boundary with `agent-verify` | B's countersign: `agent-verify` authors bundles, this group owns engine + gate |

Everything else is implemented: the frozen edits (`0.2`) were approved by A on 2026-11-08 as a purely
additive diff, and `3.3`, `4.1`–`4.3`, `6.1`–`6.3` landed on top of it. The engine is exercised both
directly (`app/audit/runner.py::audit_state`, `scripts/audit_demo.py`) and through the transport
(`POST /runs/{thread_id}/stages/audit`).