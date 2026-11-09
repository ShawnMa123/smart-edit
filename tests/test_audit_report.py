"""Task 3.2 — coverage conservation and the outcome matrix."""

from __future__ import annotations

import pytest

from app.audit.report import (
    COMPLETE,
    CURRENT,
    OUTCOME_FINDINGS,
    OUTCOME_NEEDS_INPUT,
    OUTCOME_NONE,
    OUTCOME_UNABLE,
    PARTIAL,
    STALE,
    AuditReportError,
    mark_stale,
    summarise,
)
from app.rules.types import (
    FAILED,
    FINDING,
    NEEDS_INPUT,
    NOT_APPLICABLE,
    PASS,
    UNABLE_TO_ASSESS,
    CheckResult,
    Unit,
)

UNITS = [Unit(check_id=f"U-{index}", family="schema") for index in range(4)]
BASELINE = {"snapshot_digest": "digest-1", "schema_version": "abc123", "bundle_versions": {"guarantee-core": "1.0.0"}}


def _results(*statuses: str) -> list[CheckResult]:
    return [
        CheckResult(check_id=unit.check_id, status=status) for unit, status in zip(UNITS, statuses)
    ]


def test_counts_are_conserved_and_baseline_is_recorded():
    report = summarise(UNITS, _results(PASS, FINDING, NOT_APPLICABLE, PASS), **BASELINE)

    assert report["planned"] == 4
    assert sum(report["counts"].values()) == 4
    assert report["snapshot_digest"] == "digest-1"
    assert report["schema_version"] == "abc123"
    assert report["bundle_versions"] == {"guarantee-core": "1.0.0"}
    assert report["engine_version"]
    assert report["freshness"] == CURRENT


def test_all_settled_units_are_complete():
    report = summarise(UNITS, _results(PASS, PASS, FINDING, NOT_APPLICABLE), **BASELINE)

    assert report["completion"] == COMPLETE
    assert report["outcome"] == OUTCOME_FINDINGS


def test_pass_plus_failed_is_never_no_findings():
    report = summarise(UNITS, _results(PASS, PASS, PASS, FAILED), **BASELINE)

    assert report["outcome"] == OUTCOME_UNABLE
    assert report["completion"] == PARTIAL
    assert report["counts"][FAILED] == 1


def test_needs_input_outranks_unable_but_not_findings():
    needs = summarise(UNITS, _results(PASS, NEEDS_INPUT, UNABLE_TO_ASSESS, PASS), **BASELINE)
    assert needs["outcome"] == OUTCOME_NEEDS_INPUT
    assert needs["completion"] == PARTIAL

    findings = summarise(UNITS, _results(FINDING, NEEDS_INPUT, PASS, PASS), **BASELINE)
    assert findings["outcome"] == OUTCOME_FINDINGS


def test_clean_run_reports_no_findings_not_compliance():
    report = summarise(UNITS, _results(PASS, PASS, PASS, NOT_APPLICABLE), **BASELINE)

    assert report["outcome"] == OUTCOME_NONE
    assert report["completion"] == COMPLETE


def test_everything_not_applicable_is_unable_to_assess():
    report = summarise(UNITS, _results(*[NOT_APPLICABLE] * 4), **BASELINE)

    assert report["outcome"] == OUTCOME_UNABLE
    assert "no_applicable_checks" in report["reasons"]
    assert report["completion"] == COMPLETE


def test_reasons_are_collected_for_ungoverned_states():
    results = [
        CheckResult(check_id="U-0", status=NEEDS_INPUT, reason_code="unconfirmed"),
        CheckResult(check_id="U-1", status=FAILED, reason_code="encoding_failed"),
        CheckResult(check_id="U-2", status=PASS),
        CheckResult(check_id="U-3", status=PASS),
    ]
    report = summarise(UNITS, results, **BASELINE)

    assert report["reasons"] == ["encoding_failed", "unconfirmed"]


def test_missing_result_is_refused():
    with pytest.raises(AuditReportError, match="no result"):
        summarise(UNITS, _results(PASS, PASS)[:2], **BASELINE)


def test_unplanned_result_is_refused():
    extra = _results(PASS, PASS, PASS, PASS) + [CheckResult(check_id="U-99", status=PASS)]
    with pytest.raises(AuditReportError, match="unplanned"):
        summarise(UNITS, extra, **BASELINE)


def test_empty_plan_is_refused():
    with pytest.raises(AuditReportError, match="empty"):
        summarise([], [], **BASELINE)


def test_coverage_counts_only_assessed_units():
    """`not_applicable` is never counted as assessed — this is the 'no findings ≠ compliant' guard."""
    report = summarise(UNITS, _results(PASS, FINDING, NOT_APPLICABLE, NOT_APPLICABLE), **BASELINE)

    assert report["coverage"] == {"assessed": 2, "not_applicable": 2, "unsettled": 0, "ratio": 0.5}


def test_coverage_separates_unsettled_units():
    report = summarise(UNITS, _results(PASS, NEEDS_INPUT, UNABLE_TO_ASSESS, FAILED), **BASELINE)

    assert report["coverage"] == {"assessed": 1, "not_applicable": 0, "unsettled": 3, "ratio": 0.25}


def test_coverage_is_zero_when_everything_is_not_applicable():
    report = summarise(UNITS, _results(*[NOT_APPLICABLE] * 4), **BASELINE)

    assert report["coverage"]["assessed"] == 0
    assert report["coverage"]["ratio"] == 0.0
    assert report["outcome"] == OUTCOME_UNABLE


def test_marking_stale_keeps_the_report_readable():
    report = summarise(UNITS, _results(FINDING, PASS, PASS, PASS), **BASELINE)

    same = mark_stale(report, "digest-1")
    assert same["freshness"] == CURRENT

    stale = mark_stale(report, "digest-2")
    assert stale["freshness"] == STALE
    assert stale["freshness_reasons"] == ["snapshot_changed"]
    assert stale["snapshot_digest"] == "digest-1", "the report keeps the snapshot it audited"
    assert stale["outcome"] == report["outcome"]