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
    "screening",
    "retrieving",
    "local_retrieval",
    "web_search",
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
    "general_web",
    # Statute text from the external legal-corpus service (knowledge-statute-retrieval).
    "statute",
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


class RetrievalLayer(Strict):
    layer: Literal["local", "rag", "web", "statute"]
    status: Literal["ok", "failed", "skipped", "blocked"]
    detail: str | None = None
    retrieved_at: str | None = None
    # How many items this layer returned; `None` means "not measured" (`statute-recall`).
    hits: int | None = None


Route = Literal["published", "statute", "document", "general_web", "handoff", "none"]
WebStatus = Literal["off", "skipped", "ok", "blocked", "failed"]


class WebSummary(Strict):
    """Why the web layer did or did not contribute to this answer (design D5)."""

    requested: bool = False
    status: WebStatus = "off"
    reason: str | None = None
    hint: str | None = None


class ModelCapability(Strict):
    configured: bool
    label: str | None = None
    approved_processor: bool = False


class LayerCapability(Strict):
    local: bool = True
    approved_web: bool = False
    general_web: bool = False
    statute: bool = False


class StatuteCapability(Strict):
    """Live view of the statute corpus; `None` fields mean "not measured", never "zero"."""

    enabled: bool = False
    reachable: bool = False
    documents: int | None = None
    chunks: int | None = None
    index_version: str | None = None
    # Jurisdictions the corpus actually covers. `None` = not measured; never a fixed guess list.
    jurisdictions: list[str] | None = None


class EgressCapability(Strict):
    policy_version: str = "unset"
    allowed_domains: int = 0
    loaded: bool = False


class WebCapability(Strict):
    provider: Literal["off", "fixture", "http"] = "off"
    # Deployment policy for the web fallback (`knowledge-simple-ask`): the panel starts from this.
    default_on: bool = False


class KnowledgePresets(Strict):
    """Optional UI presets shipped with the knowledge config; `None` means "not configured"."""

    jurisdictions: list[str] | None = None
    suggested_questions: list[str] | None = None


class Capabilities(Strict):
    """Read-only deployment view; never contains keys, URLs or user identifiers."""

    model: ModelCapability
    layers: LayerCapability
    egress: EgressCapability
    web: WebCapability
    statute: StatuteCapability = Field(default_factory=StatuteCapability)
    presets: KnowledgePresets = Field(default_factory=KnowledgePresets)


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
    # Retrieval transparency (knowledge-retrieval-layers): which layers ran and how they ended.
    retrieval: list[RetrievalLayer] = Field(default_factory=list)
    # Which model processor produced the answer ("fixture" or the configured provider label).
    processor: str | None = None
    # Which path produced this answer (design D4); null only for records written before this field.
    route: Route | None = None
    # Why the web layer did or did not contribute (design D5).
    web: WebSummary | None = None
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
    # Per-run opt-in for the web retrieval layer; default off (knowledge-retrieval-layers).
    web_search: bool = False
    # Who chose that value: the user's toggle or the deployment default (`knowledge-simple-ask`).
    web_search_source: Literal["user", "default"] | None = None


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