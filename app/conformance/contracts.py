"""Report contract for the template-conformance audit.

The report is what the panel renders and what an auditor re-reads later, so it separates:

- `results` — one row per config requirement, with the quote the model used;
- `missing_fields` — from the deterministic extractor only;
- `limitations` — why something was not assessed (model unavailable, text truncated, extraction
  not run, quote not locatable);
- `provenance` — model, prompt version, config fingerprint, snapshot revision, redaction steps.

Every field is explicit: there is no "passed" flag without a quote and no silent fallback.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["must", "should", "info"]
ResultStatus = Literal["pass", "finding", "unable_to_assess"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
Outcome = Literal["findings_present", "no_findings", "needs_input", "unable_to_assess"]
Completion = Literal["complete", "partial"]


class ConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_id: str
    version: str
    name: str
    document_types: list[str] = Field(default_factory=list)
    language: str = "auto"
    description: str = ""
    requirement_count: int = 0
    required_fields: list[str] = Field(default_factory=list)
    content_sha256: str = ""


class RequirementDetail(BaseModel):
    """One calibration requirement, as the panel's read-only config inspector shows it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    level: Level
    check: str | None = None
    evidence_hint: str | None = None
    suggestion: str | None = None


class ConfigDetail(BaseModel):
    """Published config with its requirements; read-only, never an edit surface."""

    model_config = ConfigDict(extra="forbid")

    config_id: str
    version: str
    name: str
    document_types: list[str] = Field(default_factory=list)
    language: str = "auto"
    description: str = ""
    extraction_profile: str | None = None
    requirement_count: int = 0
    required_fields: list[str] = Field(default_factory=list)
    content_sha256: str = ""
    generation: dict = Field(default_factory=dict)
    requirements: list[RequirementDetail] = Field(default_factory=list)


class ConformanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    document_id: str
    config_id: str
    # Pin what the operator was looking at; a mismatch is `stale_snapshot`, never a silent re-read.
    draft_id: str | None = None
    expected_revision: int | None = None
    expected_content_sha256: str | None = None
    language: str | None = None


class ConformanceRun(BaseModel):
    """Named with the module prefix: `Run` would collide with the assistant schema in OpenAPI."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    stage: str
    created_at: str
    finished_at: str | None = None
    report_id: str | None = None
    error: str | None = None
    progress: dict = Field(default_factory=dict)


# Internal ergonomics alias; OpenAPI uses the class name (`ConformanceRun`), so this cannot collide
# with the assistant's own `Run` schema.
Run = ConformanceRun


class SnapshotInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    draft_id: str | None = None
    title: str | None = None
    revision: int | None = None
    content_sha256: str | None = None
    analyzed_chars: int = 0
    truncated: bool = False


class RedactionStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    count: int
    sample: str


class RedactionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool = False
    total: int = 0
    note: str = ""
    steps: list[RedactionStep] = Field(default_factory=list)


class RequirementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    level: Level
    status: ResultStatus
    severity: Literal["Warning", "Info"] = "Info"
    gate_type: Literal["advisory", "human_review"] = "advisory"
    explanation: str = ""
    suggestion: str | None = None
    quote: str | None = None
    block_index: int | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    reason_codes: list[str] = Field(default_factory=list)


class MissingField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    note: str | None = None


class Counts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: int = 0
    passed: int = 0
    findings: int = 0
    unable_to_assess: int = 0
    missing_fields: int = 0
    coverage_ratio: float = 0.0


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    prompt_version: str
    config_sha256: str
    extraction_status: Literal["deterministic", "not_run", "failed"] = "not_run"
    extraction_profile: str | None = None
    model_calls: int = 0
    duration_ms: int = 0
    redaction: RedactionInfo = Field(default_factory=RedactionInfo)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    run_id: str
    outcome: Outcome
    completion: Completion
    config: ConfigSummary
    snapshot: SnapshotInfo
    summary: str = ""
    summary_note: str = ""
    results: list[RequirementResult] = Field(default_factory=list)
    missing_fields: list[MissingField] = Field(default_factory=list)
    counts: Counts = Field(default_factory=Counts)
    limitations: list[dict] = Field(default_factory=list)
    provenance: Provenance


__all__ = [
    "Completion",
    "ConfigDetail",
    "ConfigSummary",
    "ConformanceRequest",
    "ConformanceRun",
    "Counts",
    "Level",
    "MissingField",
    "Outcome",
    "Provenance",
    "RedactionInfo",
    "RedactionStep",
    "Report",
    "RequirementDetail",
    "RequirementResult",
    "ResultStatus",
    "Run",
    "RunStatus",
    "SnapshotInfo",
]