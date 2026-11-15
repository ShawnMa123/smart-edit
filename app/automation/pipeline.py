"""Deterministic rewrite pipeline (fixture transformer) for the run core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.automation.facts import assess_facts
from app.automation.operations import build_fixture_proposal
from app.automation.run_schemas import OutcomeDetails, RewriteInput
from app.automation.schemas import ChangeProposal, FixtureProposalCreate


@dataclass(frozen=True)
class RewriteOutcome:
    outcome: str
    proposal: ChangeProposal | None = None
    details: OutcomeDetails | None = None
    risk_flags: tuple[str, ...] = ()


def build_rewrite(
    draft: dict[str, Any], raw_input: dict[str, Any], *, proposal_id: str
) -> RewriteOutcome:
    """Turn a rewrite input into a proposal or a business outcome; no model is called."""
    payload = RewriteInput.model_validate(raw_input)
    if payload.intent not in ("polish", "clarify", "replace_clause", "replace_text"):
        raise ValueError("unsupported rewrite intent")
    replacement = payload.replacement_text or "This clause has been reviewed."
    fixture = FixtureProposalCreate(
        document_id=draft["document_id"],
        draft_id=draft["draft_id"],
        search_text=payload.search_text,
        replacement_text=replacement,
        intent=payload.intent,
    )
    proposal = build_fixture_proposal(draft, fixture, proposal_id=proposal_id)
    assessment = assess_facts(
        proposal.preview.before_text,
        proposal.preview.after_text,
        intent=payload.intent,
    )
    if assessment.requires_clarification:
        return RewriteOutcome(
            outcome="needs_clarification",
            details=OutcomeDetails(
                reason_codes=["protected_fact_change"],
                questions=[
                    {
                        "question_id": "q_protected_fact",
                        "text": "This wording changes a protected fact. Confirm the intended value before rewriting.",
                        "field_ids": [],
                    }
                ],
            ),
            risk_flags=assessment.risk_flags,
        )
    proposal.risk_flags = list(assessment.risk_flags)
    return RewriteOutcome(
        outcome="proposal_ready",
        proposal=proposal,
        risk_flags=assessment.risk_flags,
    )


__all__ = ["RewriteOutcome", "build_rewrite"]