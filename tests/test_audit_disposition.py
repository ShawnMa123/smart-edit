"""Task 7.1 — append-only disposition events."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.audit.disposition import (
    ACCEPTED,
    DISPOSITIONS,
    NEEDS_HUMAN_REVIEW,
    OPEN,
    REJECTED,
    DispositionError,
    append_event,
    latest,
    unresolved_critical,
)

AT = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)


def test_events_append_and_earlier_events_are_untouched():
    first = append_event([], finding_id="N-001", disposition=ACCEPTED, actor="ops", at=AT)
    second = append_event(first, finding_id="N-001", disposition=REJECTED, actor="compliance", at=AT)

    assert [event["disposition"] for event in second] == [ACCEPTED, REJECTED]
    assert first == [second[0]], "the earlier list must not be mutated"
    assert second[0]["actor"] == "ops"
    assert second[1]["at"] == AT.isoformat()


def test_rejecting_a_critical_finding_requires_a_reason():
    with pytest.raises(DispositionError, match="requires a reason"):
        append_event([], finding_id="N-001", disposition=REJECTED, actor="ops", severity="critical")

    accepted = append_event(
        [], finding_id="N-001", disposition=REJECTED, actor="ops", severity="critical", reason="checked with trade ops"
    )
    assert accepted[0]["reason"] == "checked with trade ops"

    # A non-critical rejection may omit the reason.
    assert append_event([], finding_id="N-002", disposition=REJECTED, actor="ops", severity="warn")


def test_unknown_disposition_and_missing_identity_are_refused():
    with pytest.raises(DispositionError, match="unknown disposition"):
        append_event([], finding_id="N-001", disposition="dismissed", actor="ops")
    with pytest.raises(DispositionError, match="finding_id"):
        append_event([], finding_id="", disposition=OPEN, actor="ops")
    with pytest.raises(DispositionError, match="actor"):
        append_event([], finding_id="N-001", disposition=OPEN, actor="")


def test_every_disposition_value_is_accepted():
    for disposition in DISPOSITIONS:
        events = append_event([], finding_id="N-001", disposition=disposition, actor="ops", reason="r")
        assert events[0]["disposition"] == disposition


def test_latest_returns_the_last_event():
    events = [
        {"finding_id": "N-001", "disposition": OPEN},
        {"finding_id": "N-002", "disposition": ACCEPTED},
        {"finding_id": "N-001", "disposition": REJECTED},
    ]

    assert latest(events, "N-001") == REJECTED
    assert latest(events, "N-002") == ACCEPTED
    assert latest(events, "N-003") is None


def test_unresolved_critical_lists_only_open_criticals():
    findings = [
        {"id": "N-001", "severity": "critical"},
        {"id": "N-002", "severity": "critical"},
        {"id": "N-003", "severity": "warn"},
    ]
    events = [{"finding_id": "N-001", "disposition": NEEDS_HUMAN_REVIEW}]

    assert unresolved_critical(findings, events) == ["N-002"]