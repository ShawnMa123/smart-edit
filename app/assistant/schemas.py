"""Pydantic DTOs for the knowledge assistant (task 0.1).

The shapes follow `AI_assistance_reqirement.md` §7–8. `extra="forbid"` is deliberate: a client that
invents a field (e.g. `owner_user_id`, `model`, `tools`) must be rejected, not silently ignored.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Outcome = Literal[
    "answered",
    "needs_clarification",
    "insufficient_evidence",
    "unable_to_assess",
    "needs_handoff",
]
SupportLevel = Literal["strong", "qualified", "insufficient", "not_applicable"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
RunStage = Literal[
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
]
Role = Literal["user", "assistant"]
Visibility = Literal["visible", "redacted"]
SourceType = Literal[
    "product_manual",
    "trade_rule",
    "internal_policy",
    "document_snapshot",
    "attachment",
    "approved_web",
]
Rating = Literal["helpful", "not_helpful"]
FeedbackCategory = Literal["incorrect", "wrong_citation", "outdated", "irrelevant", "unclear"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Selection(Strict):
    node_id: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    selected_text: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def _ordered(self) -> "Selection":
        if self.start_offset >= self.end_offset:
            raise ValueError("start_offset must be < end_offset")
        return self


class Claim(Strict):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: Literal["fact", "interpretation"]
    citation_ids: list[str] = Field(default_factory=list)


class Citation(Strict):
    id: str = Field(min_length=1)
    source_type: SourceType
    title: str
    source_version: str
    locator: dict[str, Any] = Field(default_factory=dict)


class Answer(Strict):
    schema_version: Literal["1.0"] = "1.0"
    outcome: Outcome
    language: Literal["zh-CN", "en"]
    support_level: SupportLevel
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    context_stale: bool = False
    handoff_target: Literal["automation", "standards_audit", "regulatory_advice"] | None = None


class ErrorBody(Strict):
    code: str
    message: str
    request_id: str
    retryable: bool = False
    field_errors: list[dict[str, str]] | None = None


class SnapshotCreate(Strict):
    document_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    content_sha256: str = Field(min_length=16, max_length=128)
    version_label: str | None = Field(default=None, max_length=120)


class Snapshot(Strict):
    id: str
    workspace_id: str
    document_id: str
    content_sha256: str
    version_label: str | None = None
    created_by: str
    created_at: str


class SessionCreate(Strict):
    workspace_id: str = Field(min_length=1, max_length=120)
    locale: Literal["zh-CN", "en"]
    document_id: str | None = None
    snapshot_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _pairs(self) -> "SessionCreate":
        if bool(self.document_id) != bool(self.snapshot_id):
            raise ValueError("document_id and snapshot_id must be provided together")
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("attachment_ids must be unique")
        return self


class Session(Strict):
    id: str
    workspace_id: str
    owner_user_id: str
    document_id: str | None = None
    snapshot_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    locale: Literal["zh-CN", "en"]
    status: Literal["active", "archived"] = "active"
    context_stale: bool = False
    created_at: str


class RunCreate(Strict):
    question: str = Field(min_length=1, max_length=4000)
    selection: Selection | None = None
    applicable_on: str | None = Field(default=None, max_length=20)
    jurisdiction_codes: list[str] = Field(default_factory=list, max_length=20)
    rule_version: str | None = Field(default=None, max_length=120)


class Run(Strict):
    id: str
    session_id: str
    user_message_id: str
    status: RunStatus
    stage: RunStage
    attempt: int = 0
    created_at: str
    deadline_at: str
    started_at: str | None = None
    finished_at: str | None = None
    assistant_message_id: str | None = None
    result: Answer | None = None
    error: ErrorBody | None = None


class RunAccepted(Run):
    poll_after_ms: int = 1000


class Message(Strict):
    id: str
    session_id: str
    run_id: str
    role: Role
    visibility: Visibility = "visible"
    question: str | None = None
    answer: Answer | None = None
    created_at: str


class MessagePage(Strict):
    items: list[Message]
    next_cursor: str | None = None


class SessionPage(Strict):
    items: list[Session]
    next_cursor: str | None = None


class EvidenceDetail(Strict):
    citation_id: str
    source_type: SourceType
    title: str
    source_version: str
    excerpt: str
    locator: dict[str, Any] = Field(default_factory=dict)
    effective_from: str | None = None
    effective_to: str | None = None
    retrieved_at: str | None = None


class FeedbackInput(Strict):
    rating: Rating
    categories: list[FeedbackCategory] = Field(default_factory=list, max_length=5)
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _categories(self) -> "FeedbackInput":
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("categories must be unique")
        return self


class Feedback(Strict):
    id: str
    message_id: str
    rating: Rating
    categories: list[FeedbackCategory] = Field(default_factory=list)
    comment: str | None = None
    created_at: str
    updated_at: str


class CancelDecision(Strict):
    run_id: str
    status: Literal["cancelled"]
    cancelled_at: str