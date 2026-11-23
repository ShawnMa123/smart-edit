"""DTOs and enums for the legal review module (spec `AI-Law_agent_reqirement.md` §8.2).

L1 slice: the deterministic check subset. snake_case, strict enums, no unknown fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── enums ──────────────────────────────────────────────────────────────────────
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
CheckStatus = Literal["pass", "finding", "not_applicable", "needs_input", "unable_to_assess", "failed"]
Severity = Literal["Critical", "Warning", "Info"]
GateType = Literal["advisory", "human_review", "hard_block"]
Method = Literal["deterministic", "semantic", "legal"]
Disposition = Literal["open", "accepted", "rejected", "needs_human_review"]
FactState = Literal["confirmed", "missing", "unconfirmed"]
# Document scan (`legal-document-risk-scan`): one contract, two scopes.
Scope = Literal["question", "document"]
Basis = Literal["rule", "statute", "web"]

TARGET_OPERATIONS = ("submit_version", "start_approval", "formal_export", "handoff", "formal_mapping")


# ── request ────────────────────────────────────────────────────────────────────
class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    document_id: str
    # `question` scope keeps the L1 contract; a document scan resolves the draft itself.
    snapshot_id: str = ""
    facts_version_id: str = ""
    modes: list[Method] = Field(min_length=1)
    attachment_refs: list[dict] = Field(default_factory=list, max_length=5)
    # Legal mode only: the question sent to the statute service (`/v1/chat`). The deterministic
    # path never reads it; a legal review without a question is `needs_input`, never a pass.
    question: str | None = None
    applicable_on: str | None = None
    jurisdiction_codes: list[str] = Field(default_factory=list)

    # ── document scan (`scope="document"`) ────────────────────────────────────
    scope: Scope = "question"
    draft_id: str | None = None
    # Optional pin: the revision the user was looking at. A mismatch is `stale_snapshot`.
    expected_revision: int | None = None
    expected_content_sha256: str | None = None
    business_type: str | None = None
    # The user's choice for the outbound web leg; `None` means "deployment default".
    web_search: bool | None = None


# ── anchors ────────────────────────────────────────────────────────────────────
class DocumentAnchor(BaseModel):
    """Where in the draft a finding applies. `quote` is always a substring of the draft text."""

    model_config = ConfigDict(extra="forbid")

    clause_id: str
    block_index: int
    start_cp: int
    end_cp: int
    quote: str = ""


class EvidenceAnchor(BaseModel):
    """A statute or web citation. Kept apart from document anchors so the UI cannot confuse
    "this part of the draft" with "this article"."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str | None = None
    doc_id: str | None = None
    article_label: str | None = None
    jurisdiction: str | None = None
    effective_from: str | None = None
    title: str | None = None
    source_version: str | None = None
    excerpt: str | None = None
    url: str | None = None
    unverified: bool = False


# ── rule contract ──────────────────────────────────────────────────────────────
class RuleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    version: str


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    method: Method
    scope_key: str
    status: CheckStatus
    rule_refs: list[RuleRef] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    # Document scan only (`legal-document-risk-scan`).
    clause_id: str | None = None
    evidence_count: int = 0
    search_queries: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    check_id: str
    method: Method
    category: str
    severity: Severity
    gate_type: GateType
    target_operations: list[str] = Field(default_factory=list)
    title: str
    explanation: str
    anchors: list[EvidenceAnchor] = Field(default_factory=list)
    document_anchors: list[DocumentAnchor] = Field(default_factory=list)
    suggestion: str | None = None
    basis: Basis = "rule"
    rule_refs: list[RuleRef] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    applicability: dict = Field(default_factory=dict)
    support_level: str = "not_applicable"
    disposition: Disposition = "open"
    version: int = 1


# ── run ────────────────────────────────────────────────────────────────────────
class ReviewRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    stage: str
    created_at: str
    deadline_at: str
    report_id: str | None = None
    error: str | None = None
    finished_at: str | None = None
    # Document scans are asynchronous; the panel polls this for a progress line.
    progress: dict = Field(default_factory=dict)


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    run_id: str
    completion: Literal["complete", "partial"]
    outcome: Literal["findings_present", "no_findings", "needs_input", "unable_to_assess"]
    findings: list[Finding] = Field(default_factory=list)
    coverage: list[CheckResult] = Field(default_factory=list)
    limitations: list[dict] = Field(default_factory=list)
    # Document scan only; empty for `question` scope so the old contract stays unchanged.
    snapshot: dict = Field(default_factory=dict)
    coverage_summary: dict = Field(default_factory=dict)
    retrieval: dict = Field(default_factory=dict)
    gate: dict = Field(default_factory=dict)


__all__ = [
    "Basis",
    "CheckResult",
    "CheckStatus",
    "Disposition",
    "DocumentAnchor",
    "EvidenceAnchor",
    "FactState",
    "Finding",
    "GateType",
    "Method",
    "ReviewCreate",
    "ReviewReport",
    "ReviewRun",
    "RuleRef",
    "RunStatus",
    "Scope",
    "Severity",
    "TARGET_OPERATIONS",
]
