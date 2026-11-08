"""Backfill plan for standalone (three-tier) triggering.

Sources: `openspec/changes/agent-normalize/design.md` §10,
`openspec/changes/poc-skeleton/design.md` §7 (`STAGE_TARGETS`).

- An unregistered target MUST be **409**, never silently widened to "run the full chain"
- A missing prerequisite must be **refused**, never answered with an empty result
"""

from __future__ import annotations

from app.stages import STAGE_TARGETS


def plan_standalone(target: str, state: dict) -> dict:
    """Return the backfill plan; when it cannot run, return a structured refusal (`status` = HTTP)."""
    spec = STAGE_TARGETS.get(target)
    if spec is None:
        return {
            "status": 409,
            "error": "unknown_stage",
            "detail": f"unregistered stage target: {target}",
            "registered": sorted(STAGE_TARGETS),
        }

    done = {
        report.get("stage")
        for report in state.get("stages") or []
        if report.get("status") == "done"
    }
    backfill = [stage for stage in spec.requires_stages if stage not in done]

    covered: set[str] = set()
    for stage in backfill:
        covered.update(STAGE_TARGETS[stage].produces)
    missing = [key for key in spec.requires_keys if key not in covered and not state.get(key)]
    if missing:
        return {
            "status": 409,
            "error": "missing_prerequisite",
            "missing": missing,
            "detail": f"missing prerequisite keys {missing}, refusing to run (no empty result)",
        }

    return {
        "status": 200,
        "target": target,
        "chain": backfill + [target],
        "backfill": backfill,
    }