"""Tasks 5.1-5.4 — the operation gate."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.audit.gate import evaluate, evaluate_gate, store_decision
from app.audit.policy import (
    ALLOWED,
    BLOCKED,
    FORMAL_EXPORT,
    FORMAL_MAPPING,
    HANDOFF,
    INDETERMINATE,
    OPERATIONS,
    POLICY,
    SAVE_DRAFT,
    START_APPROVAL,
    SUBMIT_VERSION,
    GateError,
    policy_for,
)
from app.rules.types import FAILED, FINDING, NEEDS_INPUT, NOT_APPLICABLE, PASS, UNABLE_TO_ASSESS

DIGEST = "digest-candidate"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _report(**counts) -> dict:
    base = {PASS: 0, FINDING: 0, NOT_APPLICABLE: 0, NEEDS_INPUT: 0, UNABLE_TO_ASSESS: 0, FAILED: 0}
    base.update(counts)
    return {
        "planned": sum(base.values()),
        "counts": base,
        "completion": "complete",
        "outcome": "no_findings",
        "freshness": "current",
        "snapshot_digest": DIGEST,
    }


def _hard_block(operation: str = START_APPROVAL, **over) -> dict:
    finding = {
        "id": "N-001",
        "severity": "critical",
        "gate_type": "hard_block",
        "method": "deterministic",
        "target_operations": [operation],
    }
    finding.update(over)
    return finding


def _gate(report, **kwargs) -> dict:
    kwargs.setdefault("operation", START_APPROVAL)
    kwargs.setdefault("candidate_digest", DIGEST)
    kwargs.setdefault("now", NOW)
    return evaluate_gate(report, **kwargs)


def test_policy_covers_every_operation_and_drafts_are_ungated():
    """5.1"""
    assert set(POLICY) == set(OPERATIONS)
    assert policy_for(SAVE_DRAFT).content_gate is False
    assert policy_for(FORMAL_MAPPING).unsupported_reason == "no_message_type_bundle"
    with pytest.raises(GateError):
        policy_for("publish_everything")


def test_clean_report_is_allowed():
    """5.2"""
    decision = _gate(_report(**{PASS: 12, NOT_APPLICABLE: 1}))

    assert decision["decision"] == ALLOWED
    assert decision["operation"] == START_APPROVAL
    assert decision["candidate_content_sha256"] == DIGEST
    assert decision["policy_revision"]
    assert decision["evaluated_at"] == NOW.isoformat()


def test_deterministic_hard_block_blocks_the_named_operation_only():
    """5.2"""
    blocked = _gate(_report(**{PASS: 11, FINDING: 1}), findings=[_hard_block(START_APPROVAL)])
    submit = _gate(
        _report(**{PASS: 11, FINDING: 1}),
        operation=SUBMIT_VERSION,
        findings=[_hard_block(START_APPROVAL)],
    )

    assert blocked["decision"] == BLOCKED
    assert blocked["reason_codes"] == ["hard_block"]
    assert blocked["authorized_finding_ids"] == ["N-001"]
    assert submit["decision"] == ALLOWED


def test_advisory_findings_never_block_but_unresolved_critical_does():
    """5.2 — severity is not blocking; an unresolved critical finding stops approval."""
    advisory = _gate(
        _report(**{PASS: 11, FINDING: 1}),
        findings=[_hard_block(gate_type="advisory", severity="warn")],
    )
    critical = _gate(
        _report(**{PASS: 11, FINDING: 1}),
        findings=[_hard_block(gate_type="advisory", severity="critical")],
    )

    assert advisory["decision"] == ALLOWED
    assert critical["decision"] == BLOCKED
    assert critical["reason_codes"] == ["unresolved_critical"]


def test_needs_input_blocks_approval_but_not_version_submission():
    """5.2 / 5.1 — the policy table, not the severity, decides."""
    approval = _gate(_report(**{PASS: 10, NEEDS_INPUT: 3}))
    submit = _gate(_report(**{PASS: 10, NEEDS_INPUT: 3}), operation=SUBMIT_VERSION)

    assert approval["decision"] == BLOCKED
    assert approval["reason_codes"] == ["needs_input"]

    assert submit["decision"] == ALLOWED
    assert "gaps_listed" in submit["reason_codes"]


def test_failed_check_blocks_and_unable_is_indeterminate():
    """5.2"""
    failed = _gate(_report(**{PASS: 9, FAILED: 1}))
    unable = _gate(_report(**{PASS: 9, UNABLE_TO_ASSESS: 1}))

    assert failed["decision"] == BLOCKED
    assert failed["reason_codes"] == ["check_failed"]
    assert unable["decision"] == INDETERMINATE
    assert unable["reason_codes"] == ["unable_to_assess"]


def test_resolved_critical_finding_allows_approval_and_latest_event_wins():
    finding = _hard_block(gate_type="advisory", severity="critical")
    report = _report(**{PASS: 11, FINDING: 1})

    allowed = _gate(
        report,
        findings=[finding],
        dispositions=[{"finding_id": "N-001", "disposition": "rejected", "reason": "checked with ops"}],
    )
    reopened = _gate(
        report,
        findings=[finding],
        dispositions=[
            {"finding_id": "N-001", "disposition": "rejected"},
            {"finding_id": "N-001", "disposition": "open"},
        ],
    )

    assert allowed["decision"] == ALLOWED
    assert reopened["decision"] == BLOCKED


def test_unsupported_operation_is_indeterminate_not_allowed():
    """5.2 — formal mapping has no bundle, so it can never be allowed by default."""
    decision = _gate(_report(**{PASS: 12}), operation=FORMAL_MAPPING)

    assert decision["decision"] == INDETERMINATE
    assert decision["reason_codes"] == ["no_message_type_bundle"]


def test_stale_or_wrong_candidate_is_indeterminate():
    """5.3"""
    wrong_candidate = _gate(_report(**{PASS: 12}), candidate_digest="a-different-digest")
    stale = _gate({**_report(**{PASS: 12}), "freshness": "stale"})

    assert wrong_candidate["decision"] == INDETERMINATE
    assert wrong_candidate["reason_codes"] == ["stale_report"]
    assert stale["decision"] == INDETERMINATE


def test_missing_report_and_unknown_operation():
    assert evaluate({}, HANDOFF, DIGEST)["reason_codes"] == ["no_audit_report"]
    with pytest.raises(GateError):
        evaluate({}, "approve_by_email", DIGEST)


def test_evaluate_reads_state_and_ignores_client_claims():
    """5.3 — a client-supplied verdict cannot decide."""
    state = {
        "verification": {"audit": _report(**{PASS: 11, FINDING: 1})},
        "findings": [_hard_block()],
        "gate": {"decision": ALLOWED},
    }

    decision = evaluate(state, START_APPROVAL, DIGEST, now=NOW)

    assert decision["decision"] == BLOCKED


def test_decision_is_stored_on_the_run():
    """5.4"""
    update = store_decision({}, _gate(_report(**{PASS: 12})))

    assert set(update) == {"gate"}
    assert update["gate"]["decision"] == ALLOWED
    for key in (
        "decision",
        "operation",
        "candidate_content_sha256",
        "policy_revision",
        "evaluated_at",
        "reason_codes",
        "authorized_finding_ids",
    ):
        assert key in update["gate"]


def test_coverage_thresholds_and_transparency_fields():
    """REVIEW.md decision 1 (adopted default): R1 / R2 / R3 plus the decision's transparency fields."""

    def report_with(planned: int, assessed: int, na: int, **counts) -> dict:
        base = {
            PASS: assessed,
            FINDING: 0,
            NOT_APPLICABLE: na,
            NEEDS_INPUT: 0,
            UNABLE_TO_ASSESS: 0,
            FAILED: 0,
        }
        base.update(counts)
        return {
            "planned": planned,
            "counts": base,
            "coverage": {
                "assessed": assessed,
                "not_applicable": na,
                "unsettled": planned - assessed - na,
                "ratio": round(assessed / planned, 3),
            },
            "completion": "complete",
            "outcome": "no_findings",
            "freshness": "current",
            "snapshot_digest": DIGEST,
        }

    nothing_assessed = _gate(report_with(51, 0, 51))
    barely = _gate(report_with(51, 10, 41))
    partial = _gate(report_with(51, 25, 26))
    well_covered = _gate(report_with(51, 33, 18))

    assert nothing_assessed["decision"] == INDETERMINATE
    assert nothing_assessed["reason_codes"] == ["no_assessed_checks"]

    assert barely["decision"] == INDETERMINATE
    assert barely["reason_codes"] == ["limited_coverage"]

    assert partial["decision"] == ALLOWED
    assert partial["reason_codes"] == ["limited_coverage"]

    assert well_covered["decision"] == ALLOWED
    assert "limited_coverage" not in well_covered["reason_codes"]

    # The decision always carries what it is allowing.
    assert well_covered["coverage"]["assessed"] == 33
    assert well_covered["open_gaps"] == 0
    assert well_covered["advisory_finding_ids"] == []
    assert well_covered["unsupported_capability"] is None


def test_discussion_version_and_draft_are_not_coverage_gated():
    """Coverage protects "this document is ready", not the discussion-version flow (decision 2)."""
    nearly_empty = {
        "planned": 51,
        "counts": {
            PASS: 1,
            FINDING: 0,
            NOT_APPLICABLE: 50,
            NEEDS_INPUT: 0,
            UNABLE_TO_ASSESS: 0,
            FAILED: 0,
        },
        "coverage": {"assessed": 1, "not_applicable": 50, "unsettled": 0, "ratio": 0.02},
        "completion": "complete",
        "outcome": "no_findings",
        "freshness": "current",
        "snapshot_digest": DIGEST,
    }

    assert _gate(nearly_empty, operation=SUBMIT_VERSION)["decision"] == ALLOWED
    assert _gate(nearly_empty, operation=SAVE_DRAFT)["decision"] == ALLOWED


def test_open_gaps_and_advisories_are_reported():
    report = _report(**{PASS: 10, NEEDS_INPUT: 3})
    decision = _gate(
        report,
        operation=SUBMIT_VERSION,
        findings=[_hard_block(gate_type="advisory", severity="warn")],
    )

    assert decision["decision"] == ALLOWED
    assert decision["open_gaps"] == 3
    assert decision["advisory_finding_ids"] == ["N-001"]


def test_unsupported_capability_is_named():
    decision = _gate(_report(**{PASS: 12}), operation=FORMAL_MAPPING)
    assert decision["unsupported_capability"] == "no_message_type_bundle"


def test_formal_export_and_handoff_follow_approval_policy():
    for operation in (FORMAL_EXPORT, HANDOFF):
        assert _gate(_report(**{PASS: 10, NEEDS_INPUT: 2}), operation=operation)["decision"] == BLOCKED
        assert _gate(_report(**{PASS: 12}), operation=operation)["decision"] == ALLOWED