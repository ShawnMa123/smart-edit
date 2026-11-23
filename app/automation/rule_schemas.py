"""Contracts for Bank Operations automation rules: template kind → downstream + trust level."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.automation.registry_schemas import BodyIssue
from app.automation.schemas import Strict

RuleTrigger = Literal["final_approval", "manual"]
RuleMode = Literal["shadow", "needs_review", "auto_send"]


class RuleCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    template_name: str = Field(min_length=1, max_length=120)
    connector_id: str = Field(min_length=1, max_length=128)
    trigger: RuleTrigger = "final_approval"
    # New rules start in shadow: they record "would send" but never call the downstream.
    mode: RuleMode = "shadow"
    required: bool = True
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    department_id: str | None = Field(default=None, max_length=128)


class RuleUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    connector_id: str | None = Field(default=None, max_length=128)
    trigger: RuleTrigger | None = None
    mode: RuleMode | None = None
    required: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None


class RuleModeUpdate(Strict):
    mode: RuleMode


class RuleView(Strict):
    rule_id: str
    name: str
    department_id: str | None = None
    template_name: str
    connector_id: str
    connector_name: str | None = None
    trigger: RuleTrigger
    mode: RuleMode
    required: bool
    priority: int
    enabled: bool
    disabled_at: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_by: str
    created_at: str
    updated_at: str


class RulePage(Strict):
    items: list[RuleView] = Field(default_factory=list)


class RuleDryRunRequest(Strict):
    document_id: str = Field(min_length=1, max_length=128)


class RuleDryRunResult(Strict):
    rule_id: str
    template_id: str
    template_name: str
    connector_id: str
    mode: RuleMode
    url: str
    method: str
    would_send: dict[str, Any] = Field(default_factory=dict)
    issues: list[BodyIssue] = Field(default_factory=list)
    refusal: str | None = None