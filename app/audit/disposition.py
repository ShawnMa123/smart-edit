"""Append-only human disposition of findings (design D9, AI-audit AUD-16).

Disposition records *handling*, not fixing: accepting a finding never changes the unit's state, never
edits the document and never counts as a rule waiver. Events are append-only because the trail is the
reason this group exists.
"""

from __future__ import annotations

from datetime import datetime, timezone

OPEN = "open"
ACCEPTED = "accepted"
REJECTED = "rejected"
NEEDS_HUMAN_REVIEW = "needs_human_review"

DISPOSITIONS = (OPEN, ACCEPTED, REJECTED, NEEDS_HUMAN_REVIEW)


class DispositionError(ValueError):
    """The disposition request is not acceptable (unknown value, missing reason for a critical reject)."""

    def __init__(self, message: str, *, code: str = "INVALID_DISPOSITION") -> None:
        super().__init__(message)
        self.code = code


def append_event(
    events: list[dict],
    *,
    finding_id: str,
    disposition: str,
    actor: str,
    severity: str | None = None,
    reason: str | None = None,
    at: datetime | None = None,
    snapshot_digest: str | None = None,
) -> list[dict]:
    """Return a new event list with one appended event. Earlier events are never modified.

    `snapshot_digest` binds the decision to the audit snapshot whose finding it handled; a new
    audit that reuses an id cannot inherit it.
    """
    if not isinstance(finding_id, str) or not finding_id.strip():
        raise DispositionError("finding_id is required")
    if not isinstance(disposition, str) or disposition not in DISPOSITIONS:
        raise DispositionError(f"unknown disposition {disposition!r}; expected one of {DISPOSITIONS}")
    if not isinstance(actor, str) or not actor.strip():
        raise DispositionError("actor is required")
    if reason is not None and not isinstance(reason, str):
        raise DispositionError("reason must be a string")
    if snapshot_digest is not None and not isinstance(snapshot_digest, str):
        raise DispositionError("snapshot_digest must be a string")
    if disposition == REJECTED and severity == "critical" and not (reason or "").strip():
        raise DispositionError(
            "rejecting a critical finding requires a reason", code="REASON_REQUIRED"
        )

    event = {
        "finding_id": finding_id,
        "disposition": disposition,
        "reason": (reason or "").strip() or None,
        "actor": actor,
        "at": (at or datetime.now(timezone.utc)).isoformat(),
    }
    if snapshot_digest:
        event["snapshot_digest"] = snapshot_digest
    return [*events, event]


def latest(events: list[dict], finding_id: str) -> str | None:
    """Latest disposition for a finding, or None when it was never handled."""
    current = None
    for event in events:
        if event.get("finding_id") == finding_id:
            current = event.get("disposition")
    return current


def unresolved_critical(findings: list[dict], events: list[dict]) -> list[str]:
    """Critical findings with no accepted/rejected/needs_human_review decision yet."""
    resolved = {ACCEPTED, REJECTED, NEEDS_HUMAN_REVIEW}
    open_critical = []
    for finding in findings:
        if finding.get("severity") != "critical":
            continue
        finding_id = str(finding.get("id") or "")
        if latest(events, finding_id) not in resolved:
            open_critical.append(finding_id or "<unidentified>")
    return open_critical