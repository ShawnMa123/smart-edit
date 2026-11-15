"""Automation contracts: immutable proposal, decision, apply and receipt."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Anchor(Strict):
    snapshot_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    start_cp: int = Field(ge=0)
    end_cp: int = Field(ge=1)
    quote_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _ordered(self) -> "Anchor":
        if self.end_cp <= self.start_cp:
            raise ValueError("end_cp must be greater than start_cp")
        return self


class ReplaceTextOperation(Strict):
    op: Literal["replace_text"]
    anchor: Anchor
    replacement_text: str = Field(max_length=100_000)


class ProposalContext(Strict):
    document_id: str
    draft_id: str
    revision: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    variables_version: int = Field(ge=1)
    authorization_version: str


class ProposalPreview(Strict):
    before_text: str
    after_text: str
    summary: str = "replace one anchored passage"


class ReviewReceipt(Strict):
    receipt_id: str
    verdict: Literal["pass", "repair", "abstain"]
    validator_version: str
    checked_claim_ids: list[str] = Field(default_factory=list)


class ChangeProposal(Strict):
    proposal_id: str
    context: ProposalContext
    operations: list[ReplaceTextOperation] = Field(min_length=1)
    preview: ProposalPreview
    risk_flags: list[str] = Field(default_factory=list)
    review_receipt: ReviewReceipt
    expires_at: str
    disposition: Literal["open", "accepted", "rejected"] = "open"
    application_status: Literal["not_applied", "applied", "undone"] = "not_applied"
    applicability: Literal["current", "stale", "expired", "unavailable"] = "current"
    revision: int = Field(default=1, ge=1)


class ProposalDecision(Strict):
    decision: Literal["accepted", "rejected"]
    reason: str | None = Field(default=None, max_length=1000)


class ApplyRequest(Strict):
    proposal_id: str
    expected_snapshot_id: str
    expected_draft_revision: int = Field(ge=1)
    lock_id: str
    fencing_token: int = Field(ge=1)
    acknowledged_risk_codes: list[str] = Field(default_factory=list)


class UndoRequest(Strict):
    expected_draft_revision: int = Field(ge=1)
    lock_id: str
    fencing_token: int = Field(ge=1)


class ApplyReceipt(Strict):
    receipt_id: str
    proposal_id: str
    previous_revision: int
    new_revision: int
    new_checkpoint_id: str
    content_sha256: str
    variables_version: int
    actor_user_id: str
    applied_at: str
    reversal_of_receipt_id: str | None = None


class FixtureProposalCreate(Strict):
    document_id: str
    draft_id: str
    search_text: str | None = Field(default=None, max_length=4000)
    replacement_text: str = Field(default="This clause has been reviewed.", max_length=4000)
    intent: Literal["polish", "clarify", "replace_clause", "replace_text"] = "replace_text"
    expires_in_seconds: int = Field(default=3600, ge=60, le=86_400)


class ApiErrorBody(Strict):
    code: str
    message: str
    request_id: str
    retryable: bool = False
    details: list[dict[str, Any]] | None = None


__all__ = [
    "Anchor",
    "ApiErrorBody",
    "ApplyReceipt",
    "ApplyRequest",
    "ChangeProposal",
    "FixtureProposalCreate",
    "ProposalContext",
    "ProposalDecision",
    "ProposalPreview",
    "ReplaceTextOperation",
    "ReviewReceipt",
    "Strict",
    "UndoRequest",
]