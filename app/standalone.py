"""Backfill plan for standalone (three-tier) triggering.

Sources: `openspec/changes/agent-normalize/design.md` §10,
`openspec/changes/poc-skeleton/design.md` §13 (`STAGE_TARGETS`, `BACKFILL`).

- An unregistered target MUST be **409**, never silently widened to "run the full chain"
- A missing prerequisite must be **refused**, never answered with an empty result
- Re-running a target MUST clear only that target's previous conclusions; `stages` / `trail`
  are append-only history.

Compatibility note: `agent3` defaults to `raw` in this build because that is what the existing
console uses when the user only pasted source text. Passing `input_mode="enriched"` selects the
full `parse -> extract -> normalize` backfill from the spec matrix. The default is the only
deliberate deviation from the table in §13; it keeps the currently shipped frontend behaviour.
"""

from __future__ import annotations

from app.stages import AGENT_TARGETS, ENRICHED_CHAIN, RAW_BACKFILL, STAGE_TARGETS

INPUT_MODES = ("raw", "enriched")


def _target_stages(resolved: str, spec, input_mode: str) -> tuple[str, ...]:
    if resolved == "agent3":
        return RAW_BACKFILL if input_mode == "raw" else ENRICHED_CHAIN
    return spec.requires_stages


def plan_standalone(target: str, state: dict, *, input_mode: str = "raw") -> dict:
    """Return the backfill plan; when it cannot run, return a structured refusal (`status` = HTTP)."""
    # `agent4` -> `audit`: an agent id means its registered target, never a silently widened chain.
    resolved = AGENT_TARGETS.get(target, target)
    spec = STAGE_TARGETS.get(resolved)
    if spec is None:
        return {
            "status": 409,
            "error": "unknown_stage",
            "refused": True,
            "agent": target,
            "missing": [],
            "reason": f"unregistered stage target: {target}",
            "detail": f"unregistered stage target: {target}",
            "registered": sorted(STAGE_TARGETS),
        }

    if input_mode not in INPUT_MODES:
        return {
            "status": 409,
            "error": "REFUSED",
            "refused": True,
            "agent": resolved,
            "detail": f"unknown input_mode {input_mode!r}; expected one of {INPUT_MODES}",
            "reason": f"unknown input_mode {input_mode!r}",
            "missing": [],
        }

    # `stages` is append-only history; the *latest* report for a stage decides whether it is done.
    # Treating any earlier `done` as permanent would skip a stage that later failed.
    latest: dict[str, str | None] = {}
    for report in state.get("stages") or []:
        latest[str(report.get("stage"))] = report.get("status")
    done = {stage for stage, status in latest.items() if status == "done"}

    required_stages = _target_stages(resolved, spec, input_mode)

    # A prerequisite this build does not implement cannot be backfilled; refusing is the only
    # honest answer ("run the full chain" would fabricate a stage that does not exist).
    unimplemented = [stage for stage in required_stages if stage not in STAGE_TARGETS]
    if unimplemented:
        return {
            "status": 409,
            "error": "REFUSED",
            "refused": True,
            "agent": resolved,
            "missing": unimplemented,
            "reason": (
                f"prerequisite stage(s) {unimplemented} are not implemented in this build; "
                f"refusing to run {resolved}"
            ),
            "detail": (
                f"prerequisite stage(s) {unimplemented} are not implemented in this build; "
                f"refusing to run {resolved}"
            ),
        }

    backfill = [stage for stage in required_stages if stage not in done]

    covered: set[str] = set()
    for stage in backfill:
        covered.update(STAGE_TARGETS[stage].produces)
    missing = [key for key in spec.requires_keys if key not in covered and not state.get(key)]
    if missing:
        return {
            "status": 409,
            "error": "missing_prerequisite",
            "refused": True,
            "agent": resolved,
            "missing": missing,
            "reason": f"missing prerequisite keys {missing}",
            "detail": f"missing prerequisite keys {missing}, refusing to run (no empty result)",
        }

    return {
        "status": 200,
        "target": resolved,
        "requested": target,
        "input_mode": input_mode if resolved == "agent3" else None,
        "chain": backfill + [resolved],
        "backfill": backfill,
    }


def clear_previous_outputs(state: dict, target: str) -> dict:
    """Clear only one target's previous conclusions; `stages` / `trail` are never touched.

    Returning a partial update (instead of mutating) keeps this usable by both the chain
    executor and a future graph node. The chain executor applies it with `merge_update`.
    """
    resolved = AGENT_TARGETS.get(target, target)
    update: dict = {}

    if resolved in ("normalize", "agent1"):
        normalization = [
            finding
            for finding in state.get("findings") or []
            if finding.get("source") == "normalization"
        ]
        if normalization:
            update["findings"] = [
                finding
                for finding in state.get("findings") or []
                if finding.get("source") != "normalization"
            ]
        # Human-confirmed values are not this stage's conclusion to discard: a re-import must not
        # silently overwrite them (document-import / 已确认字段不被导入覆盖).
        confirmed = {
            key: value
            for key, value in (state.get("fields") or {}).items()
            if isinstance(value, dict) and (value.get("confirmed") or value.get("edited_by_user"))
        }
        extra_confirmed = {
            key: value
            for key, value in (state.get("extra_fields") or {}).items()
            if isinstance(value, dict) and (value.get("confirmed") or value.get("edited_by_user"))
        }
        update.update(
            {"fields": confirmed, "extra_fields": extra_confirmed, "business_type": None}
        )
    elif resolved == "extract":
        update["_candidates"] = []
    elif resolved == "agent2":
        update["findings"] = [
            finding
            for finding in state.get("findings") or []
            if finding.get("source") != "business"
        ]
    elif resolved == "agent3":
        update["findings"] = [
            finding
            for finding in state.get("findings") or []
            if finding.get("source") != "regulatory"
        ]
        update.update({"legal": None, "retrieved": []})
    elif resolved == "audit":
        update.update({"verification": None, "gate": None, "export": None})

    return update


__all__ = ["INPUT_MODES", "clear_previous_outputs", "plan_standalone"]
