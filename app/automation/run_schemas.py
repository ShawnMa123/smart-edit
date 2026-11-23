"""Automation run/result contracts (document-host-foundation follow-up)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.automation.schemas import Strict

TaskType = Literal[
    "extract",
    "fill",
    "define_variable",
    "rewrite",
    "compare",
    "compose_import",
    "map_api",
    "voice_command",
]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
RunStage = Literal["queued", "context", "planning", "processing", "reviewing", "publishing", "done"]
RunCompletion = Literal["complete", "partial"]
RunOutcome = Literal[
    "candidates_ready",
    "proposal_ready",
    "comparison_ready",
    "mapping_ready",
    "voice_plan_ready",
    "no_changes",
    "needs_clarification",
    "insufficient_evidence",
    "needs_handoff",
    "unable_to_process",
]
RewriteIntent = Literal["polish", "clarify", "replace_clause", "replace_text"]


class RunCreate(Strict):
    task_type: TaskType
    document_id: str = Field(min_length=1, max_length=128)
    draft_id: str = Field(min_length=1, max_length=128)
    input: dict[str, Any] = Field(default_factory=dict)


class RewriteInput(Strict):
    intent: RewriteIntent = "replace_text"
    search_text: str | None = Field(default=None, max_length=4000)
    replacement_text: str | None = Field(default=None, max_length=4000)
    instruction: str | None = Field(default=None, max_length=4000)


class AutomationRun(Strict):
    run_id: str
    task_type: TaskType
    document_id: str
    draft_id: str
    status: RunStatus
    stage: RunStage
    revision: int = Field(ge=1)
    created_at: str
    deadline_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result_id: str | None = None
    error: dict[str, Any] | None = None

    @property
    def etag(self) -> str:
        return f"run-{self.revision}"


class RunPage(Strict):
    items: list[AutomationRun]


class OutcomeDetails(Strict):
    reason_codes: list[str] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    suggested_group: str | None = None


class AutomationResult(Strict):
    result_id: str
    run_id: str
    completion: RunCompletion
    outcome: RunOutcome
    payload: dict[str, Any]
    limitations: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


class RunCancel(Strict):
    reason: str | None = Field(default=None, max_length=1000)


__all__ = [
    "AutomationResult",
    "AutomationRun",
    "OutcomeDetails",
    "RewriteInput",
    "RewriteIntent",
    "RunCancel",
    "RunCompletion",
    "RunCreate",
    "RunOutcome",
    "RunPage",
    "RunStage",
    "RunStatus",
    "TaskType",
]