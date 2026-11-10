"""`audit` node (task 6.1): call the pure engine, number findings, write one `StageReport`.

Four rules this node obeys, and nothing else:

1. **No business judgement here** — every verdict comes from `app/audit/*` and `app/rules/*`.
2. **No model call** — `model_calls=0` on the stage report, and the engine has no provider.
3. **A broken audit still returns a stage report** (`failed` + reason) instead of raising, so the run
   is not lost; it also clears `verification`, because a previous report must not be readable as if it
   were this run's audit.
4. **No gate decision.** The audit produces evidence; `gate` is a separate command (`app/nodes/gate.py`)
   and only that command records a decision. A missing `gate` means "nobody asked", never "allowed".
"""

from __future__ import annotations

try:
    from langgraph.types import Overwrite
except ImportError:  # pragma: no cover - older langgraph layout
    from langgraph.graph.message import Overwrite  # type: ignore[no-redef]

from app.audit.project import finding_draft, project_issue, to_verification
from app.audit.runner import audit_state
from app.audit.snapshot import snapshot_digest
from app.findings import materialize_findings
from app.stages import stage_report
from app.trail import record, record_many

AUDIT_STAGE = "audit"
AUDIT_AGENT = "agent4"


def audit_node(
    state: dict,
    *,
    schema=None,
    bundles=None,
    templates=None,
    template_reference: dict | None = None,
) -> dict:
    """Run one audit over `state` and return the node update.

    Template-driven audit is opt-in: pass `template_reference={"template_id": …}` (the stage trigger does
    that when the caller names a template) or `templates=[…]`. With neither, the audit runs on the base
    schema and the published rule packs, and the report says `template_not_requested`.
    """
    digest = snapshot_digest(state)
    try:
        outcome = audit_state(
            # Business findings belong to the snapshot that produced them; this audit is about to
            # replace them. Feeding the previous snapshot's rows back in makes the anchor check
            # flag its own predecessor (e.g. a field that has since been removed).
            {**state, "findings": _non_business_findings(state)},
            snapshot_digest=digest,
            schema=schema,
            bundles=bundles,
            templates=templates,
            template_reference=template_reference,
        )
    except Exception as exc:  # AuditRunError / BundleError / PlanError / SchemaError / …
        return _failed(state, f"audit refused: {exc}")

    report, results, units = outcome["report"], outcome["results"], outcome["units"]
    by_id = {unit.check_id: unit for unit in units}

    drafts: list[dict] = []
    check_ids: list[str] = []
    for result in results:
        draft = finding_draft(result, by_id[result.check_id])
        if draft is not None:
            drafts.append(draft)
            check_ids.append(result.check_id)

    # Numbering restarts for this snapshot: an id must never be inherited from a previous audit
    # (a stale disposition bound to B-001 would otherwise resolve a different finding).
    materialized = materialize_findings(
        {**state, "findings": []}, drafts, agent=AUDIT_AGENT, stage=AUDIT_STAGE
    )
    id_by_check = {
        check_id: finding["id"]
        for check_id, finding in zip(check_ids, materialized["findings"])
    }

    issues = [
        project_issue(
            result, by_id[result.check_id], finding_id=id_by_check.get(result.check_id)
        )
        for result in results
    ]
    findings = [
        {**finding, "id": id_by_check.get(finding["check_id"])} for finding in report["findings"]
    ]
    verification = to_verification(report, issues=issues, findings=findings)

    update = {
        "verification": verification,
        # Findings are bound to the snapshot they came from: replace the audit's own rows, never
        # append. Normalization/regulatory findings belong to other producers and stay. An old
        # gate decision is invalidated by writing `None` — a new audit has not been approved.
        "findings": Overwrite(_non_business_findings(state) + materialized["findings"]),
        "gate": None,
        "stages": [
            stage_report(
                AUDIT_STAGE,
                status="done",
                produced=len(materialized["findings"]),
                model_calls=0,
                agent=AUDIT_AGENT,
            )
        ],
        "trail": _trail(state, report, digest, materialized["trail"]),
    }

    return update


def _non_business_findings(state: dict) -> list[dict]:
    """Findings that this audit does not replace (normalization / regulatory)."""
    return [
        finding
        for finding in state.get("findings") or []
        if isinstance(finding, dict) and finding.get("source") != "business"
    ]


def _failed(state: dict, reason: str) -> dict:
    """The audit could not run: a stage report with a reason, no verification, no findings.

    A previous decision is invalidated (never written as a new one): leaving an old `allowed` next to
    a failed audit is exactly the "uncertainty answered as approval" failure this group prevents.
    """
    return {
        "verification": None,
        "gate": None,
        "findings": Overwrite(_non_business_findings(state)),
        "stages": [
            stage_report(
                AUDIT_STAGE, status="failed", reason=reason, model_calls=0, agent=AUDIT_AGENT
            )
        ],
        **record(
            state,
            agent=AUDIT_AGENT,
            stage=AUDIT_STAGE,
            op="pass",
            detail={"reason": reason, "audited": False},
        ),
    }


def _trail(state: dict, report: dict, digest: str, emit_entries: list[dict]) -> list[dict]:
    """One receipt for the audit itself, then one `emit` entry per finding (ids allocated once each)."""
    template = report.get("template") or {}
    receipt = record(
        state,
        agent=AUDIT_AGENT,
        stage=AUDIT_STAGE,
        op="pass",
        detail={
            "planned": report["planned"],
            "outcome": report["outcome"],
            "completion": report["completion"],
            "assessed": report["coverage"]["assessed"],
            "snapshot_digest": digest,
            "model_calls": 0,
            "template_id": template.get("template_id"),
            "template_version": template.get("version"),
            "template_reason": template.get("reason"),
        },
    )["trail"]
    # Allocate the emit ids against the receipt, or the two calls would hand out the same numbers.
    after_receipt = {**state, "trail": [*(state.get("trail") or []), *receipt]}
    emitted = record_many(
        after_receipt, agent=AUDIT_AGENT, stage=AUDIT_STAGE, entries=emit_entries
    )["trail"]
    return [*receipt, *emitted]