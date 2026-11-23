"""Pure automation run state rules (no HTTP, no SQLite)."""

from __future__ import annotations

RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "timed_out")
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
ACTIVE_STATUSES = frozenset({"queued", "running"})
RUN_STAGES = ("queued", "context", "planning", "processing", "reviewing", "publishing", "done")

_ALLOWED: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled", "timed_out", "failed"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "timed_out"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "timed_out": frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in _ALLOWED.get(current, frozenset())


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def stage_after(current: str) -> str:
    try:
        return RUN_STAGES[min(RUN_STAGES.index(current) + 1, len(RUN_STAGES) - 1)]
    except ValueError:
        return "context"


__all__ = [
    "ACTIVE_STATUSES",
    "RUN_STAGES",
    "RUN_STATUSES",
    "TERMINAL_STATUSES",
    "can_transition",
    "is_active",
    "is_terminal",
    "stage_after",
]