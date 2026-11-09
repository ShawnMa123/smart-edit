"""Agent 2 adapter ( **not** an Agent 2 implementation).

Agent 2's business rules (`requirements.yaml`, field checks, business parameters) are owned by a
different change (`agent-verify`). The orchestrator still needs a node at that position, and the
only honest placeholder is one that reports "not checked" instead of returning `findings=[]` —
an empty finding list would make the gate read "no problems" when nothing was checked.

`app/graph_factory.build_graph(agent2=...)` accepts the real node; when it lands, only the
factory call changes. This module deliberately contains no rule ids and no fabricated findings.
"""

from __future__ import annotations

from app.stages import stage_report
from app.trail import record

AGENT2_STAGE = "agent2"
AGENT2_AGENT = "agent2"


def agent2_node(state: dict) -> dict:
    """Refuse with a structured `StageReport`, never invent a verdict."""
    missing = [key for key in ("fields", "business_type") if not state.get(key)]
    if missing:
        reason = f"missing prerequisite keys {missing}, refusing to run (no empty result)"
    else:
        reason = "agent2 is not implemented in this build; refusing to fabricate findings"

    return {
        "stages": [
            stage_report(
                AGENT2_STAGE,
                status="failed",
                reason=reason,
                model_calls=0,
                agent=AGENT2_AGENT,
            )
        ],
        **record(
            state,
            agent=AGENT2_AGENT,
            stage=AGENT2_STAGE,
            op="pass",
            detail={"reason": reason, "implemented": False},
        ),
    }


__all__ = ["AGENT2_AGENT", "AGENT2_STAGE", "agent2_node"]
