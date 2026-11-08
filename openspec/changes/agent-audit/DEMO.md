# Demo record — standards audit group (`agent-audit`)

Evidence for tasks 9.1–9.4. Artifacts are English per an explicit instruction
(`design.md` Open Questions 3).

## Environment observed

| Item | Value |
|---|---|
| Engine version | `1.0.0` |
| Policy revision | `2026-11-08.2` (coverage thresholds + decision transparency) |
| Schema version (hash of `app/configs/fields.yaml` projection) | `044a959e73af` (15 fields) |
| Rule bundle | `guarantee-core` v`1.0.0`, content hash `f27c8614ed03` |
| Planned check units for a guarantee document | **51** (schema units + 6 rules + 6 evidence checks) |
| Model calls during an audit | **0** |

```bash
.venv/bin/python -m pytest tests/test_rule_schema.py tests/test_audit_bind.py \
    tests/test_rule_dsl.py tests/test_rule_engine.py tests/test_rule_bundles.py \
    tests/test_audit_planner.py tests/test_audit_report.py tests/test_audit_gate.py \
    tests/test_audit_disposition.py tests/test_audit_evidence.py \
    tests/test_audit_acceptance.py -q
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

Test suite after this work: **233 passed**.

## 9.3 Staleness (AT-17)

```
gate start_approval on a report audited for digest-clean, asked about digest-after-edit
  -> indeterminate, reason_codes ['stale_report']
```

And `mark_stale()` keeps the report readable: it records `freshness=stale`,
`freshness_reasons=['snapshot_changed']`, and still names the snapshot it audited
(`snapshot_digest=digest-clean`). Findings are never re-pointed at newer text.

## What this build deliberately does **not** do

- **Semantic checks (AUD-10) are not implemented.** There is no model in the audit path, so no
  `method="semantic"` finding can be produced by this build. The report shape carries `method` so
  enabling it later is additive, not a rewrite.
- Variables (AUD-07), template and internal-policy bundles (AUD-08/09/11), draft-export rules
  (AUD-15), applying suggested edits (AUD-17), organisation permissions (AUD-18/19), rule governance
  and the management API (AUD-20/§11), async jobs, leases and fencing (AUD-21), retention (AUD-22),
  audit UI surfaces (AUD-23), incremental audits (AUD-24), and the `/audit/*` HTTP surface (§10).
- Evidence checks that need other agents' outputs (citation support, conclusion conflict, coverage
  declaration) report `not_applicable` with reason `requires_agent_regulatory_output` — they are never
  silently skipped.

## Blocked tasks and what unblocks them

| Task | Blocked by |
|---|---|
| `0.1` boundary with `agent-verify` | B's countersign: `agent-verify` authors bundles, this group owns engine + gate |
| `0.2` frozen edits | three-person approval for 5 optional `Issue`/`VerificationReport` fields + `agent4.standalone` flip |
| `3.3` report baseline in `verification.audit` | the same `VerificationReport.audit` field |
| `4.1`–`4.3` finding projection | the four optional `Issue` fields |
| `6.1`–`6.3` node and envelope | `agent4.standalone` flip + `verification.audit` |

Until then the engine is exercised through `app/audit/runner.py::audit_state()`, which is exactly what
the node will call once the sign-off lands (design Migration step 2).