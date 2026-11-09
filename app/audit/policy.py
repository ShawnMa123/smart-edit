"""Per-operation gate policy as data (design D8, AI-audit §7.2).

Severity and blocking are independent: `critical` alone never stops anything, and a semantic finding can
never appear as `hard_block`. What blocks is decided here, per protected operation.
"""

from __future__ import annotations

from dataclasses import dataclass

SAVE_DRAFT = "save_draft"
SUBMIT_VERSION = "submit_version"
START_APPROVAL = "start_approval"
FORMAL_EXPORT = "formal_export"
HANDOFF = "handoff"
FORMAL_MAPPING = "formal_mapping"

OPERATIONS = (SAVE_DRAFT, SUBMIT_VERSION, START_APPROVAL, FORMAL_EXPORT, HANDOFF, FORMAL_MAPPING)

POLICY_REVISION = "2026-11-08.2"

# Coverage thresholds (REVIEW.md decision 1; adopted as the default by A on 2026-11-08, B/C countersign
# pending). "assessed" counts units that produced `pass` or `finding` — `not_applicable` never counts.
MIN_ASSESSED_RATIO = 0.30  # below this a protected operation is indeterminate
LIMITED_COVERAGE_RATIO = 0.60  # below this the decision must carry the `limited_coverage` reason

ALLOWED = "allowed"
BLOCKED = "blocked"
INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class OperationPolicy:
    operation: str
    content_gate: bool
    block_on_hard_block: bool = True
    block_on_needs_input: bool = False
    block_on_unresolved_critical: bool = False
    # Coverage thresholds apply to operations that assert "this document is ready", not to the
    # discussion-version flow (which is *allowed* to carry gaps by policy).
    enforce_coverage: bool = True
    # A capability this build does not have turns the answer into `indeterminate`, never `allowed`.
    unsupported_reason: str | None = None


POLICY: dict[str, OperationPolicy] = {
    # Drafts are never gated on content: identity, permission and locking still apply elsewhere.
    SAVE_DRAFT: OperationPolicy(SAVE_DRAFT, content_gate=False, enforce_coverage=False),
    # Gaps are listed but do not stop a version submission; only deterministic hard blocks do.
    # A discussion version may legitimately have most checks `not_applicable`, so coverage is not
    # enforced here — see REVIEW.md decision 2.
    SUBMIT_VERSION: OperationPolicy(SUBMIT_VERSION, content_gate=True, enforce_coverage=False),
    START_APPROVAL: OperationPolicy(
        START_APPROVAL, content_gate=True, block_on_needs_input=True, block_on_unresolved_critical=True
    ),
    FORMAL_EXPORT: OperationPolicy(
        FORMAL_EXPORT, content_gate=True, block_on_needs_input=True, block_on_unresolved_critical=True
    ),
    HANDOFF: OperationPolicy(
        HANDOFF, content_gate=True, block_on_needs_input=True, block_on_unresolved_critical=True
    ),
    # No message-type bundle exists in this build, so mapping cannot be judged — say so.
    FORMAL_MAPPING: OperationPolicy(
        FORMAL_MAPPING, content_gate=True, unsupported_reason="no_message_type_bundle"
    ),
}


class GateError(ValueError):
    """The gate was asked something it cannot answer at all (for example an unknown operation)."""


def policy_for(operation: str) -> OperationPolicy:
    try:
        return POLICY[operation]
    except KeyError:
        raise GateError(f"unknown operation {operation!r}; expected one of {OPERATIONS}") from None