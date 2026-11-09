"""Export gate: decide whether a finished run may leave the system.

Spec: `orchestration` → *闸门判定*. Design: `poc-skeleton/design.md` §9.

Six checks, **all collected in a fixed order** — the gate never short-circuits, because a user
who fixes one reason must not discover the next one only after another round trip:

1. `verification` must exist and its verdict must not be `fail`
2. no `blocking` finding may still be unresolved
3. no `inferred` field may remain unconfirmed
4. every required stage must have a `done` report
5. legal escalation / unavailable coverage blocks
6. the operation gate must not be blocked or indeterminate

`verification.score` is **never read**: it is display-only. The operation gate (agent-audit
§7.2) is still asked, because it is the only component allowed to interpret rule severity for
one protected operation; this node does not trust its own reading of rule ids.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.audit.gate import evaluate as evaluate_operation
from app.audit.policy import ALLOWED, FORMAL_EXPORT
from app.audit.snapshot import snapshot_digest
from app.stages import latest_stage, stage_report
from app.state import StageReport

GATE_STAGE = "gate"

# `audit` is Agent 4's stage name in this build; the contract calls the stage `agent4`.
REQUIRED_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ingest", ("ingest",)),
    ("parse", ("parse",)),
    ("extract", ("extract",)),
    ("normalize", ("normalize",)),
    ("agent2", ("agent2",)),
    ("agent3", ("agent3",)),
    ("agent4", ("agent4", "audit")),
)


def _report(state: dict, aliases: tuple[str, ...]) -> StageReport | None:
    for stage in aliases:
        report = latest_stage(state.get("stages") or [], stage)
        if report is not None:
            return report
    return None


def _unconfirmed_inferred(fields: dict | None) -> list[str]:
    return [
        key
        for key, value in (fields or {}).items()
        if value.get("status") == "inferred" and not value.get("confirmed")
    ]


def evaluate_export_gate(
    state: dict,
    *,
    operation: str = FORMAL_EXPORT,
    now: datetime | None = None,
) -> dict:
    """Return the full gate decision; `verdict` is `pass` only when no reason was collected."""
    reasons: list[dict] = []

    def add(code: str, detail: dict | None = None) -> None:
        reasons.append({"code": code, "detail": detail or {}})

    # 1. Evidence chain.
    verification = state.get("verification")
    if not verification:
        add("VERIFICATION_MISSING")
    elif verification.get("verdict") == "fail":
        add("VERIFICATION_FAILED", {"checks": len(verification.get("checks") or [])})

    # 2. Unresolved blocking findings.
    unresolved = [
        finding.get("id")
        for finding in state.get("findings") or []
        if isinstance(finding, dict) and finding.get("blocking") and not finding.get("resolved")
    ]
    if unresolved:
        add("UNRESOLVED_BLOCKING", {"finding_ids": unresolved})

    # 3. Inferred values a human has not confirmed.
    unconfirmed = _unconfirmed_inferred(state.get("fields"))
    if unconfirmed:
        add("UNCONFIRMED_INFERRED", {"field_keys": unconfirmed})

    # 4. Required stages.
    incomplete = []
    for stage, aliases in REQUIRED_STAGES:
        report = _report(state, aliases)
        if not report or report.get("status") != "done":
            incomplete.append(
                {
                    "stage": stage,
                    "status": (report or {}).get("status"),
                    "reason": (report or {}).get("reason"),
                }
            )
    if incomplete:
        add("STAGES_INCOMPLETE", {"stages": incomplete})

    # 5. Legal escalation / unavailable coverage.
    legal = state.get("legal") or {}
    if legal.get("escalate_to_human"):
        add("LEGAL_ESCALATED")
    coverage = legal.get("coverage") or {}
    if coverage.get("unavailable"):
        add("COVERAGE_UNAVAILABLE", {"notes": coverage.get("notes") or []})

    # 6. Operation gate. Its own report may be indeterminate even when the five checks above pass.
    digest = snapshot_digest(state)
    try:
        decision = evaluate_operation(
            state,
            operation,
            digest,
            dispositions=state.get("dispositions") or (),
        )
    except Exception as exc:  # an exception is uncertainty, never a pass
        decision = {
            "decision": "indeterminate",
            "operation": operation,
            "candidate_content_sha256": digest,
            "reason_codes": [f"gate_error:{type(exc).__name__}"],
            "evaluated_at": (now or datetime.now(timezone.utc)).isoformat(),
        }
    if decision.get("decision") != ALLOWED:
        add(
            "GATE_INDETERMINATE"
            if decision.get("decision") == "indeterminate"
            else "GATE_BLOCKED",
            {"reason_codes": decision.get("reason_codes") or []},
        )

    verdict = "pass" if not reasons else "blocked"
    return {
        "verdict": verdict,
        "decision": verdict,
        "blocked": verdict == "blocked",
        "reasons": reasons,
        "reason_codes": sorted({reason["code"] for reason in reasons}),
        # Display only; the routing code never reads it.
        "score": (verification or {}).get("score"),
        "operation": operation,
        "candidate_content_sha256": digest,
        "evaluated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "audit_decision": decision,
    }


def export_gate_node(state: dict, *, operation: str = FORMAL_EXPORT) -> dict:
    """Return `{"gate": decision}` plus one `gate` stage report."""
    decision = evaluate_export_gate(state, operation=operation)
    produced = 0 if decision["verdict"] == "pass" else len(decision["reasons"])
    return {
        "gate": decision,
        "stages": [
            stage_report(
                GATE_STAGE,
                status="done" if decision["verdict"] == "pass" else "failed",
                reason=None
                if decision["verdict"] == "pass"
                else ", ".join(reason["code"] for reason in decision["reasons"]),
                produced=produced,
                model_calls=0,
            )
        ],
    }


__all__ = ["GATE_STAGE", "REQUIRED_STAGES", "evaluate_export_gate", "export_gate_node"]
