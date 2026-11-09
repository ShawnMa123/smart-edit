"""Stage registry and prerequisite checks.

Contract: `openspec/changes/poc-skeleton/design.md` §7. This is **the only place allowed to
declare "what I depend on"**. Any agent that wants to be triggered standalone must register
itself in `AGENT_SPECS` / `STAGE_TARGETS`.

Two rules:
1. **Refusal != empty result**: `require()` returns `{"refused": True, "missing": [...]}` and the
   caller writes `StageReport(failed, reason=...)`; never use `findings=[]` to mean "not run".
2. **Stage reports are append-only**: a rerun leaves several reports for the same stage, so read
   them with `latest_stage()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.state import SHARED_STAGE_OWNER, STAGE_STATUS


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str  # agent1 .. agent4 (shared stages are attributed to agent1)
    requires_stages: tuple[str, ...]  # stages that must be done first
    requires_keys: tuple[str, ...]  # state keys that must be non-empty
    produces: tuple[str, ...]  # keys this writes (cleared before a rerun)
    standalone: bool  # whether it can be triggered on its own
    cleared_on_rerun: tuple[str, ...] = ()


AGENT_SPECS = {
    "agent1": AgentSpec(
        "agent1",
        (),
        ("files",),
        ("docs", "fields", "extra_fields", "business_type", "findings"),
        True,
        ("docs", "fields", "extra_fields"),
    ),
    "agent2": AgentSpec(
        "agent2",
        ("normalize",),
        ("fields", "business_type"),
        ("findings", "stages", "trail"),
        True,
    ),
    "agent3": AgentSpec(
        "agent3",
        ("parse",),
        ("files",),
        ("findings", "legal", "retrieved", "stages", "trail"),
        True,
    ),
    "agent4": AgentSpec(
        "agent4",
        ("merge",),
        ("findings", "stages"),
        ("verification", "stages", "trail"),
        True,  # flipped with task 0.2: the audit is triggerable on its own through `audit`
    ),
}

# Stage targets: not agents, but they must be triggerable on their own
# (agent-normalize's three-tier acceptance depends on it).
# An unregistered target MUST be refused (409), never silently widened to "run the full chain".
STAGE_TARGETS = {
    "parse": AgentSpec("agent1", (), ("files",), ("docs",), True),
    "extract": AgentSpec("agent1", ("parse",), ("docs",), ("_candidates",), True),
    "normalize": AgentSpec(
        "agent1",
        ("parse", "extract"),
        ("_candidates",),
        ("fields", "extra_fields", "business_type", "findings"),
        True,
        ("fields", "extra_fields", "business_type"),
    ),
    # Agent 4's only triggerable target (task 6.2). It declares the **whole** shared layer, not just
    # `normalize`: `execute_chain` runs the plan as written and does not expand it transitively, so
    # requiring only `normalize` would run it without `docs` and fail by design.
    "audit": AgentSpec(
        "agent4",
        ("parse", "extract", "normalize"),
        ("fields",),
        ("verification", "gate", "findings"),
        True,
        ("verification", "gate"),
    ),
}
ENRICHED_CHAIN = ("parse", "extract", "normalize")

# An agent id resolves to the stage target that represents it, so `POST /runs/{id}/stages/agent4`
# means "run the audit" rather than `unknown_stage`. An agent with no registered target is still
# refused — registration, never a guess (design D5 of `frontend-console`).
AGENT_TARGETS = {
    "agent1": "normalize",
    "agent4": "audit",
}

RAW_BACKFILL = ("parse",)


def stage_report(
    stage: str,
    *,
    status: str,
    reason: str | None = None,
    produced: int = 0,
    model_calls: int = 0,
    agent: str = SHARED_STAGE_OWNER,
) -> dict:
    """Build one `StageReport`.

    `skipped` / `failed` / `partial` require a `reason` — otherwise the replay only shows
    "not run" and the user sees "parse incomplete" with no way to find out why.
    """
    if status not in STAGE_STATUS:
        raise ValueError(f"unknown stage status: {status!r}, allowed: {STAGE_STATUS}")
    if status != "done" and not reason:
        raise ValueError(f"StageReport(status={status!r}) requires a reason")
    return {
        "stage": stage,
        "agent": agent,
        "status": status,
        "reason": reason,
        "produced": produced,
        "model_calls": model_calls,
    }


def latest_stage(stages: list[dict], stage: str) -> dict | None:
    """Last report for the given stage; `None` if there is none."""
    for report in reversed(stages or []):
        if report.get("stage") == stage:
            return report
    return None


def require(state: dict, *keys: str) -> dict | None:
    """Prerequisite check. Returns `None` when satisfied, else a structured refusal.

    Returns `{"refused": True, "missing": [...]}` — **not** `{"findings": []}`.
    """
    missing = [k for k in keys if not state.get(k)]
    if missing:
        return {"refused": True, "missing": missing}
    return None