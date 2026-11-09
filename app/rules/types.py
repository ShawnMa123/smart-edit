"""Shared types for the rule engine and the audit group.

Deliberately dependency-free (no model, no HTTP, no state) so the deterministic kernel stays pure —
`tests/test_rule_engine.py` asserts this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

ENGINE_VERSION = "1.0.0"

# Per-unit states (spec: coverage accounting, six states, counts must sum to planned).
PASS = "pass"
FINDING = "finding"
NOT_APPLICABLE = "not_applicable"
NEEDS_INPUT = "needs_input"
UNABLE_TO_ASSESS = "unable_to_assess"
FAILED = "failed"

UNIT_STATUSES = (PASS, FINDING, NOT_APPLICABLE, NEEDS_INPUT, UNABLE_TO_ASSESS, FAILED)
# States that still count as "the check ran and produced a verdict".
SETTLED_STATUSES = (PASS, FINDING, NOT_APPLICABLE)

Method = Literal["deterministic", "semantic"]
Family = Literal["schema", "rule", "evidence", "template"]


class Tri(Enum):
    """Three-valued logic (AI-audit §5.1): `unknown` is never `pass`."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class RuleEvaluationError(RuntimeError):
    """A rule could not be evaluated (bad operand, unsupported feature, handler crash)."""


@dataclass(frozen=True)
class Unit:
    """One planned check. Built by the planner **before** anything is evaluated."""

    check_id: str
    family: Family
    method: Method = "deterministic"
    rule_ref: dict | None = None
    field_id: str | None = None
    required: bool = False
    scope_key: str = "document"


@dataclass
class CheckResult:
    """One unit's outcome. `finding` carries the detail the report/finding projection needs."""

    check_id: str
    status: str
    reason_code: str | None = None
    finding: dict | None = None
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in UNIT_STATUSES:
            raise ValueError(f"unknown unit status {self.status!r}")