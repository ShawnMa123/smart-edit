"""`reset` node: make the start of every validation round clean.

Contract: `openspec/changes/poc-skeleton/design.md` §9 and `orchestration` spec.

Only the reducer key `findings` needs `Overwrite`; every other loop key is a LastValue channel
and is cleared with plain assignment. `stages` and `trail` are **append-only history** and are
never cleared — a replay has to show "the second run failed after the user changed a field".
"""

from __future__ import annotations

try:  # LangGraph 1.x
    from langgraph.types import Overwrite
except ImportError:  # pragma: no cover - older layout, kept for the documented dual path
    from langgraph.graph.message import Overwrite  # type: ignore[no-redef]

from app.stages import stage_report

RESET_STAGE = "reset"


def reset_node(state: dict) -> dict:  # noqa: ARG001 - signature required by the graph
    """Return the deterministic zero for one validation round."""
    return {
        "findings": Overwrite([]),
        "legal": None,
        "retrieved": [],
        "verification": None,
        "gate": None,
        "export": None,
        "recheck": False,
        "stages": [stage_report(RESET_STAGE, status="done", produced=0, model_calls=0)],
    }


__all__ = ["RESET_STAGE", "reset_node", "Overwrite"]
