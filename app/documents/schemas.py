"""Strict request DTOs for the document host API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentCreate(Strict):
    document_id: str | None = Field(default=None, min_length=1, max_length=128)
    title: str = Field(default="Untitled document", min_length=1, max_length=200)
    content: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=200_000)
    variables: dict[str, Any] = Field(default_factory=dict)
    # NULL/absent = organisation-level document (design D4).
    department_id: str | None = Field(default=None, max_length=128)


class DraftSave(Strict):
    content: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=200_000)
    lock_id: str = Field(min_length=1, max_length=128)
    fencing_token: int = Field(ge=1)


class VariablesUpdate(Strict):
    variables: dict[str, Any]
    lock_id: str = Field(min_length=1, max_length=128)
    fencing_token: int = Field(ge=1)


class LockCreate(Strict):
    session_id: str | None = Field(default=None, max_length=128)
    lease_seconds: int = Field(default=30, ge=1, le=300)


class Heartbeat(Strict):
    lease_seconds: int = Field(default=30, ge=1, le=300)


class SubmissionCreate(Strict):
    lock_id: str = Field(min_length=1, max_length=128)
    fencing_token: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    content_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class ApprovalDecision(Strict):
    decision: Literal["approve", "return", "reject"]
    comment: str | None = Field(default=None, max_length=2000)
    expected_revision: int = Field(ge=1)


__all__ = [
    "ApprovalDecision",
    "DocumentCreate",
    "DraftSave",
    "Heartbeat",
    "LockCreate",
    "Strict",
    "SubmissionCreate",
    "VariablesUpdate",
]