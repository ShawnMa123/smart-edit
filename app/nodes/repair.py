"""Controlled repair: one bounded rerun of the branch a failed check can actually fix.

Contract: `openspec/changes/poc-skeleton/design.md` §12.

Rules that must not drift:

- `verification.score` is never read. A low score with all checks passing reruns nothing.
- Input-class failures (`input_invalid` / `source_missing` / `coverage_unavailable`) go straight to
  a human; rerunning an agent cannot invent missing source material.
- The budget is one repair pass. When it is spent, the graph goes to `hitl`.
- Only the failing branch's conclusions are cleared; `verification` stays as feedback, and
  `stages` / `trail` stay append-only.
"""

from __future__ import annotations

from app.stages import stage_report
from app.trail import record

REPAIR_STAGE = "repair"

FIXABLE_BY: dict[str, set[str]] = {
    "evidence_locatable": {"agent2", "agent3"},
    "span_locatable": {"agent2", "agent3"},
    "citation_present": {"agent3"},
    "field_key_resolvable": {"agent2"},
}
UNREPAIRABLE = {"input_invalid", "source_missing", "coverage_unavailable"}


def _checker_text(check: dict) -> str:
    return str(check.get("checker") or "").lower()


def repair_targets(verification: dict | None) -> tuple[set[str], list[dict]]:
    """Return `(branches, feedback)` for the failing checks of one report.

    Unknown failing checkers are *not* assumed repairable: an unrecognised failure is a human
    decision, not a licence to spend another model call.
    """
    branches: set[str] = set()
    feedback: list[dict] = []
    for check in (verification or {}).get("checks") or []:
        if check.get("level") != "fail":
            continue
        checker = _checker_text(check)
        if any(name in checker for name in UNREPAIRABLE):
            return set(), []
        targets: set[str] = set()
        for name, owners in FIXABLE_BY.items():
            if name in checker:
                targets |= owners
        if not targets:
            continue
        branches |= targets
        feedback.append(
            {
                "checker": check.get("checker"),
                "location": check.get("location"),
                "detail": check.get("detail"),
                # A score is not feedback; a producer needs to know what to produce.
                "expect": "re-run the producing agent with a locatable source fragment",
            }
        )
    return branches, feedback


def _clear_branches(state: dict, branches: set[str]) -> dict:
    findings = list(state.get("findings") or [])
    update: dict = {}
    if "agent2" in branches:
        findings = [finding for finding in findings if finding.get("source") != "business"]
    if "agent3" in branches:
        findings = [finding for finding in findings if finding.get("source") != "regulatory"]
        update["legal"] = None
        update["retrieved"] = []
    update["findings"] = findings
    return update


def repair_node(state: dict) -> dict:
    """Clear only the failing branch, record feedback, spend one unit of budget."""
    branches, feedback = repair_targets(state.get("verification"))
    if not branches:
        return {"requested_stages": []}

    repaired = sorted(branches)
    return {
        **_clear_branches(state, branches),
        "requested_stages": repaired,
        "repair_count": int(state.get("repair_count") or 0) + 1,
        "stages": [
            stage_report(
                REPAIR_STAGE, status="done", produced=len(feedback), model_calls=0
            )
        ],
        **record(
            state,
            agent="agent4",
            stage=REPAIR_STAGE,
            op="pass",
            after=",".join(repaired),
            detail={"targets": repaired, "feedback": feedback},
        ),
    }


def route_after_verifier(state: dict) -> str:
    """`repair` only for a fixable `fail`; everything else goes to the human."""
    verification = state.get("verification") or {}
    if verification.get("verdict") != "fail":
        return "hitl"
    if int(state.get("repair_count") or 0) >= 1:
        return "hitl"
    branches, _ = repair_targets(verification)
    return "repair" if branches else "hitl"


def route_after_repair(state: dict) -> str:
    """One branch per repair pass; agent2 wins ties (it owns the field-level evidence)."""
    requested = set(state.get("requested_stages") or [])
    if "agent2" in requested:
        return "agent2"
    if "agent3" in requested:
        return "agent3"
    return "hitl"


__all__ = [
    "FIXABLE_BY",
    "REPAIR_STAGE",
    "UNREPAIRABLE",
    "repair_node",
    "repair_targets",
    "route_after_repair",
    "route_after_verifier",
]
