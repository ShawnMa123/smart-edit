"""Contracts for automatic-dispatch jobs and document-level delivery state.

A job is one `(rule, submission, downstream)` unit of work. The document-level delivery status is
derived from its jobs: `sent` means every *required* downstream accepted the request; an optional
failure is a warning, not a blocker.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.automation.rule_schemas import RuleMode
from app.automation.schemas import Strict

JobStatus = Literal[
    "queued",
    "sending",
    "needs_review",
    "sent",
    "shadowed",
    "needs_attention",
    "cancelled",
    "skipped",
]

DeliveryStatus = Literal[
    "not_configured",
    "queued",
    "sending",
    "needs_review",
    "sent",
    "partial",
    "needs_attention",
    "shadowed",
]


class JobView(Strict):
    job_id: str
    rule_id: str
    rule_name: str | None = None
    document_id: str
    document_title: str | None = None
    submission_id: str
    template_id: str
    connector_id: str
    connector_name: str | None = None
    status: JobStatus
    mode: RuleMode
    required: bool
    attempts: int
    next_attempt_at: str | None = None
    error_code: str | None = None
    receipt_id: str | None = None
    request: dict[str, Any] | None = None
    response_excerpt: str | None = None
    created_at: str
    updated_at: str


class JobEventView(Strict):
    event_id: str
    from_status: str | None = None
    to_status: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class JobDetailView(JobView):
    events: list[JobEventView] = Field(default_factory=list)


class JobPage(Strict):
    items: list[JobView] = Field(default_factory=list)


class DeliveryRow(Strict):
    job_id: str
    rule_id: str
    connector_id: str
    connector_name: str | None = None
    status: JobStatus
    mode: RuleMode
    required: bool
    attempts: int
    error_code: str | None = None
    receipt_id: str | None = None
    updated_at: str


class DocumentDelivery(Strict):
    document_id: str
    status: DeliveryStatus
    auto_send_enabled: bool
    skipped_reason: str | None = None
    rows: list[DeliveryRow] = Field(default_factory=list)


class AutomationSettings(Strict):
    """Runtime switches the Runs/Rules panels display (the worker itself stays env-driven)."""

    auto_send_enabled: bool