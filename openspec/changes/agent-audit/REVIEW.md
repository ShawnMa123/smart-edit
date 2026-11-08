# Sign-off request — three decisions for B and C

> **What this is.** Three behaviours the standards audit group (`agent-audit`) cannot settle alone,
> because they are business-acceptance questions, not code questions. Each one changes what the screen
> will tell an operator, or what the gate will refuse.
> **Who signs.** Decision 1: C proposes, B accepts. Decision 2: B. Decision 3: C (and business if handy).
> **Why now.** Everything else in this change is built and tested (30/31 tasks, 281 tests); the tasks
> that were waiting on these three answers (`3.3`, `4.1`–`4.3`, `6.1`–`6.3`) are now implemented on the
> recommended defaults, so a "no" changes one constant or one boolean plus one test — nothing is waiting.
> **Evidence below is measured**, from `DEMO.md` runs, not estimated.

> **Status (2026-11-08, second pass).** A has implemented the recommended defaults below end to end, so
> the work is not blocked while you read this. Nothing here is final: each answer flips a constant or a
> boolean plus one test, not a rewrite. Please tick and initial the table at the end — especially if you
> disagree.

## What the current build already does (so the decisions have context)

| Sample | Planned | Assessed (pass+finding) | `not_applicable` | Unsettled (needs_input/unable/failed) | Assessed ratio | Outcome | Gate `start_approval` |
|---|---|---|---|---|---|---|---|
| Clean guarantee | 51 | 33 (33+0) | 18 | 0 | **0.647** | `no_findings` | allowed |
| `guarantee_amount` absent | 51 | 27 (26+1) | 22 | 2 | 0.529 | `findings_present` | blocked (`hard_block`) |
| Every value `inferred` | 51 | **1** (1+0) | 19 | 31 | **0.020** | `needs_input` | blocked (`needs_input`) |

Two facts worth noticing before deciding:

1. `not_applicable` is **already** separated from `pass` (an absent optional field is "not applicable",
   an unconfirmed one is "needs input", only `required` produces a finding).
2. The **report does not yet say how much was actually assessed**. A caller sees `outcome=no_findings`
   and cannot tell "51 of 51 checked" from "3 of 51 checked, the rest not applicable". The third row is
   the extreme case: **1 of 51 units assessed** and the report still says `needs_input`, not "we barely
   looked".

---

## Decision 1 — coverage threshold (this is the "no findings ≠ compliant" guard)

**Question:** when most planned checks are `not_applicable`, may a protected operation still be
`allowed`? Today: yes, unless something is `needs_input` / `failed` / `unable_to_assess`.

**Recommendation (three rules, all cheap to implement):**

| # | Rule | Decision | Reason code |
|---|---|---|---|
| R1 | `assessed == 0` | `indeterminate` | `no_assessed_checks` |
| R2 | `assessed / planned < 0.30` | `indeterminate` | `limited_coverage` |
| R3 | `0.30 ≤ ratio < 0.60` | `allowed`, but the decision carries `coverage` and the reason `limited_coverage` so the UI must print "assessed 15 of 51 planned" | — |

**Why 0.30 / 0.60:** the clean sample sits at **0.647**, so the normal demo is unaffected; the
all-`inferred` sample sits at **0.020** and the nearly-empty sample at 0.529. In other words the
recommended band separates "we looked at most of it" from "we barely looked", without touching the
clean path. These numbers are a starting point, not a law — give us different numbers and we implement
those.

**Alternatives:** (a) no threshold, rely on the UI text (cheapest, weakest); (b) only R1 (`assessed == 0`);
(c) your ratio.

**Answer:** ☐ accept R1+R2+R3 ☐ accept R1 only ☐ use these numbers instead: ____________
*Currently implemented: R1+R2+R3 with 0.30 / 0.60 (`app/audit/policy.py`).*

---

## Decision 2 — may a discussion version be submitted with gaps? (B)

**Today:** `submit_version` is **allowed** with `gaps_listed` and `open_gaps: N`; `start_approval` is
**blocked** on the same document.

**Basis:** `AI-audit §7.2` — `submit_version`: "允许讨论版本保留经政策许可的未填项；明确标记缺口；
仅已批准规则配置的硬约束阻断"; `start_approval`: "完成所有必填及确定性校验".

**The risk if nobody confirms it:** an operator reads "allowed" as "this version is fine" and stops
chasing the missing amount, because the gaps are only in a reason code.

**We will make it visible either way:** the decision will carry `open_gaps` and `advisory_finding_ids`,
so the screen can say *"submitted as discussion version — 3 gaps listed"* instead of a bare "allowed".

**Answer:** ☐ keep as described ☐ also block `submit_version` on gaps ☐ other: ____________

---

## Decision 3 — `formal_mapping` is always `indeterminate` (C / business)

**Today:** asking the gate about `formal_mapping` always answers `indeterminate`, reason
`no_message_type_bundle`.

**Why:** a message mapping cannot be judged without a published message-type bundle (MT760 etc.), and this
build has none. Guessing would be worse than refusing, and silently answering `allowed` would be a lie.

**Options:** (a) keep `indeterminate` and say "capability not available" (recommended — honest, and the
operation stays visible so nobody assumes it works); (b) remove the operation entirely (clients get an
unknown-operation error — harsher, and hides that this is a scope choice); (c) keep it but hide it in the
UI until a bundle exists.

**Answer:** ☐ (a) ☐ (b) ☐ (c) ☐ other: ____________

---

## Signatures

| Decision | B | C | Business | Date |
|---|---|---|---|---|
| 1. Coverage threshold | | | | |
| 2. Submit with gaps | | | | |
| 3. `formal_mapping` | | | | |

## Not part of this sheet (for context only)

- **`agent-verify` boundary** (B's countersign): `agent-verify` authors rule bundles, this group owns the
  engine and the gate. Tracked as `design.md` Open Questions 1 / task 0.1.
- **Frozen-file approval** (A + B + C): five optional contract fields plus the `agent4` standalone flip.
  Tracked as task 0.2 — approved and implemented by A (additive only); B / C countersign pending and
  changes nothing in the code.

All three recommended defaults are now implemented end to end: one `Issue` per planned unit, the gate
reading `verification.audit["findings"]`, and `POST /runs/{thread_id}/stages/audit` as a triggerable
stage (the audit itself decides no operation). Your answers now only decide whether the defaults change.