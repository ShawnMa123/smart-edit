# Proposal

## Why

Two documents define what this group must do, and openspec currently describes something else.

`tradeAI_requirementDesign_v2/AI-audit_reqirement.md` is titled **规则审计 Agent 功能与实现规格** and
carries AUD-01…AUD-24: field/Schema checks, template and internal-policy clauses, limited semantic
consistency, planned coverage accounting, findings with `gate_type`, an operation gate, human
disposition and rule governance. `Requirements.md` §9.1–§9.3 says the same thing at RULE-01…RULE-04
level. That is the **规范审计组**: it audits *the document* against *versioned rules*.

What openspec's `agent-audit` change specifies instead is `output-verification`: a verifier of
*other agents' evidence chains* (`schema_check`, `trail_check`, `citation_check`,
`provenance_check`…), whose own Purpose says "只回答'证据链是否成立'，不评业务对错；范围不含业务判断、
法规适用判断与主观评分". Useful, but it is not rule auditing — and nobody owns rule auditing today.

The gap already produced a real defect: with only `agent-normalize` implemented, the console's
"Rule audit" button ended up running normalization stages, so the screen promised an audit and
delivered field standardization (`editor-shell/DEMO.md` records that deviation). The same gap blocks
the gate: `gate` needs `gate_type` and a decision per protected operation, and nothing in the repo
produces either.

Why now: `agent-verify` and `agent-regulatory` are being specified in parallel, and both will assume
somebody else owns the rule engine and the gate. Deciding that identity now is cheaper than
reconciling three overlapping rule implementations later.

## What Changes

- **Identity change.** `agent-audit` becomes the **规范审计组**. Its job: audit a fixed document
  snapshot against a resolved, versioned rule bundle, and answer "is this operation allowed?".
  The evidence-chain checks it currently owns are **kept** as one internal check family
  (`evidence` family) — they now verify the audit's own inputs instead of being the group's identity.
- **Capability rename.** `output-verification` is replaced by `rule-audit` (nothing is archived yet,
  so no migration is implied; the old delta is deleted from this change).
- **POC slice, buildable on the frozen contract** (AUD ids in brackets):
  - deterministic rule engine over a closed, typed DSL with three-valued logic (AUD-02…06, §5.1–5.2);
  - field-Schema checks for the six field types the project already has
    (`amount` / `currency` / `date` / `integer` / `string` / `country`);
  - planned coverage accounting with the six per-unit states and counts that must sum to `planned`
    (AUD-12, §7.1);
  - findings carrying severity **and** `gate_type`, anchors and rule references (AUD-13);
  - an operation gate over the six protected operations, deterministic-only `hard_block`
    (AUD-14, §7.2–7.3);
  - human disposition as append-only events (AUD-16, minimal);
  - recomputability: same snapshot + same bundle + same engine version ⇒ identical report (AT-01).
- **Deferred, explicitly** (this is the part that keeps the change honest): variables AUD-07;
  template and internal-policy bundles AUD-08/09/11; semantic checks AUD-10; draft-specific export
  rules AUD-15; applying suggested edits AUD-17; organisation permissions AUD-18/19; rule governance
  and management API AUD-20/§11; async jobs, leases and fencing AUD-21; retention AUD-22; audit UI
  surfaces AUD-23; incremental audits AUD-24. The `/audit/*` HTTP surface of §10 is also deferred —
  the POC exposes the group as a stage target plus the existing `console-api` envelope.
- **Boundary with `agent-verify` — decision required.** `AI-audit §1.1` gives the audit group the
  field/Schema checks and the `GateEvaluator`; `agent-verify`'s `business-verification` currently
  claims field-value legality and requirement completeness *plus* blocking. Both cannot implement it.
  Recommended split: `agent-verify` becomes a **rule-bundle author** (business parameters, requirement
  lists, thresholds) and the audit group owns the engine, the evaluation and the gate. Needs B's
  sign-off before either side is coded; until then neither delta may implement the same check twice.
- **Contract additions — sign-off required.** Four fields on `Issue`, all optional:
  `gate_type` (`advisory` / `human_review` / `hard_block`), `target_operations`, `check_id`, `method`
  (`deterministic` / `semantic`). The frozen-contract rule is "子结构只增不改；新增字段必须可选", so this
  is admissible, but it is still a three-person decision.
- **`agent4` becomes standalone-triggerable.** Today `AGENT_SPECS["agent4"].standalone is False`
  because the group only verified other agents' output. It now audits a document, so AUD-01
  (a user starts an audit) is impossible without this flip. `app/stages.py` is signature-frozen →
  sign-off required.

**BREAKING (internal only)**: capability `output-verification` → `rule-audit`; `agent4` standalone
`False` → `True`. No external API or stored data exists to migrate.

## Capabilities

### New Capabilities

- `rule-audit`: the standards audit group — a fixed audit snapshot, a resolved versioned rule bundle,
  a closed deterministic rule engine with three-valued logic, planned coverage accounting, findings
  that carry `gate_type` and anchors, an operation gate over protected actions, append-only human
  disposition, and the recomputability guarantee. It also retains the evidence-chain check family
  (schema / trail / conflict / coverage / citation / provenance / anchor) that verifies the audit's
  own inputs.

### Modified Capabilities

None. `openspec/specs/` still holds no archived capability, so this change replaces its own
`output-verification` delta rather than modifying a published requirement set.

## Impact

- **New modules**: `app/rules/` (DSL types, three-valued evaluator, bundle loader + integrity checks),
  `app/audit/` (coverage planner, finding projection, gate evaluator), `app/nodes/audit.py`,
  `app/rules/bundles/*.yaml`
- **Reused**: `app/verifier/*` (evidence family keeps its existing checkers), `app/findings.py`
  numbering, `app/configs/fields.yaml` as the Schema source of truth
- **Frozen files touched, each needing sign-off**: `app/stages.py` (register the `audit` stage target,
  flip `agent4.standalone`), `app/state.py` (four optional `Issue` fields)
- **Consumers**: the `gate` node (now has something to read), `editor-shell` (its audit button finally
  has a real target instead of abusing `normalize`), and the future orchestrator routing
- **Tests**: engine unit tests (AT-01…AT-06 subset), coverage/conservation tests (AT-14),
  per-operation gate tests (AT-15), snapshot binding (AT-17), disposition rules (AT-18)
- **Risk — duplicate rule ownership.** If `agent-verify` keeps its own field-format checks, two
  engines will disagree on the same document. Mitigation: the boundary table above is a sign-off gate,
  and the first task is to record the decision, not to code around it.
- **Risk — the model sneaks into a deterministic path.** `AI-audit §5.2` forbids scripts, regexes and
  network calls inside rules; an LLM "just to fix wording" would forfeit AT-01 recomputability.
  Mitigation: the engine takes typed values only, and a test asserts the module imports no provider.
- **Risk — coverage accounting faked under time pressure.** The tempting shortcut is to report
  "passed" over the checks that happened to run. `AUD-12`/§7.1 forbid it (counts must sum to the
  planned set; `no_findings` must never coexist with `failed`). Mitigation: conservation tests come
  with the planner task, not at the end.
- **Risk — scope creep into the full `/audit/*` API.** §10 defines ~17 endpoints (reports, citations,
  human tasks, rule governance, gate previews). This change keeps one stage target plus the existing
  envelope; the API is a separate change once the engine is trusted.