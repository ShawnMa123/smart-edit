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

TARGET_OPERATIONS = ("submit_version", "start_approval", "formal_export", "handoff", "formal_mapping")


# ── request ────────────────────────────────────────────────────────────────────
class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    document_id: str
    snapshot_id: str
    facts_version_id: str
    modes: list[Method] = Field(min_length=1)
    attachment_refs: list[dict] = Field(default_factory=list, max_length=5)
    # Legal mode only: the question sent to the statute service (`/v1/chat`). The deterministic
    # path never reads it; a legal review without a question is `needs_input`, never a pass.
    question: str | None = None
    applicable_on: str | None = None
    jurisdiction_codes: list[str] = Field(default_factory=list)


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
    anchors: list[dict] = Field(default_factory=list)
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


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    run_id: str
    completion: Literal["complete", "partial"]
    outcome: Literal["findings_present", "no_findings", "needs_input", "unable_to_assess"]
    findings: list[Finding] = Field(default_factory=list)
    coverage: list[CheckResult] = Field(default_factory=list)
    limitations: list[dict] = Field(default_factory=list)
