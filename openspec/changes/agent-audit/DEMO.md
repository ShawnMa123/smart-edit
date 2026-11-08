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