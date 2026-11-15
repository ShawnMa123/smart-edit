"""Server-side Reviewer for automation proposals (deterministic in this build)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.automation.facts import assess_facts
from app.automation.operations import validate_structure
from app.automation.schemas import ChangeProposal, ReviewReceipt
from app.documents.errors import HostError
from app.documents.store import new_id


@dataclass(frozen=True)
class ReviewResult:
    verdict: str
    issues: tuple[str, ...]
    receipt: ReviewReceipt | None

    @property
    def passed(self) -> bool:
        return self.verdict == "pass" and self.receipt is not None


def review_proposal(proposal: ChangeProposal, draft: dict[str, Any]) -> ReviewResult:
    issues: list[str] = []
    try:
        validate_structure(proposal, draft)
    except HostError as error:
        issues.append(error.code)

    assessment = assess_facts(
        proposal.preview.before_text,
        proposal.preview.after_text,
        intent="replace_text",
    )
    if assessment.requires_clarification:
        issues.append("protected_fact_change")
    missing = sorted(set(assessment.risk_flags) - set(proposal.risk_flags))
    if missing:
        issues.append("risk_flags_missing")
    if issues:
        return ReviewResult("abstain", tuple(sorted(set(issues))), None)

    receipt = ReviewReceipt(
        receipt_id=new_id("review"),
        verdict="pass",
        validator_version="review-v1",
        checked_claim_ids=["protected_facts", "anchors", "overlap"],
    )
    return ReviewResult("pass", (), receipt)


__all__ = ["ReviewResult", "review_proposal"]