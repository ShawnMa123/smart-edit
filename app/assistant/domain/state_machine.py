"""Pure run/answer state rules (task 0.3). No FastAPI, no SQLite, no model."""

from __future__ import annotations

from app.assistant.schemas import Answer

RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "timed_out")
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
ACTIVE_STATUSES = frozenset({"queued", "running"})
RUN_STAGES = (
    "queued",
    "resolving_context",
    "analyzing",
    "retrieving",
    "composing",
    "reviewing",
    "publishing",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)

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


def validate_answer(answer: Answer) -> list[str]:
    """Structural honesty rules. Returns problem codes; an empty list means publishable."""
    problems: list[str] = []
    citation_ids = {citation.id for citation in answer.citations}

    if answer.outcome == "answered":
        if not answer.claims:
            problems.append("answered_without_claims")
        if answer.support_level not in ("strong", "qualified"):
            problems.append("answered_support_level")
        if answer.handoff_target is not None:
            problems.append("answered_with_handoff")
        for claim in answer.claims:
            if not claim.citation_ids:
                problems.append(f"claim_without_citation:{claim.id}")
            for citation_id in claim.citation_ids:
                if citation_id not in citation_ids:
                    problems.append(f"claim_unknown_citation:{claim.id}")
    else:
        if answer.claims:
            problems.append("non_answered_with_claims")
        if answer.handoff_target is not None and answer.outcome != "needs_handoff":
            problems.append("handoff_target_on_non_handoff")

    if answer.outcome == "needs_clarification":
        if not 1 <= len(answer.clarification_questions) <= 3:
            problems.append("clarification_questions")
        if answer.support_level != "not_applicable":
            problems.append("clarification_support_level")
    elif answer.clarification_questions:
        problems.append("clarification_questions_on_other_outcome")

    if answer.outcome == "needs_handoff" and answer.handoff_target is None:
        problems.append("handoff_without_target")

    if answer.outcome in ("insufficient_evidence", "unable_to_assess"):
        if answer.support_level != "insufficient":
            problems.append("insufficient_support_level")
        if not answer.limitations:
            problems.append("insufficient_without_limitation")

    return problems