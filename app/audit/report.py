"""The only place coverage counts, completion, outcome and freshness are computed (design D6).

`summarise()` asserts that the six per-unit states account for every planned unit. That assertion is the
difference between "we audited the document" and "we audited whatever happened to run".
"""

from __future__ import annotations

from app.rules.types import (
    ENGINE_VERSION,
    FAILED,
    FINDING,
    NEEDS_INPUT,
    NOT_APPLICABLE,
    PASS,
    SETTLED_STATUSES,
    UNABLE_TO_ASSESS,
    UNIT_STATUSES,
    CheckResult,
    Unit,
)

OUTCOME_FINDINGS = "findings_present"
OUTCOME_NONE = "no_findings"
OUTCOME_NEEDS_INPUT = "needs_input"
OUTCOME_UNABLE = "unable_to_assess"

COMPLETE = "complete"
PARTIAL = "partial"

CURRENT = "current"
STALE = "stale"


class AuditReportError(ValueError):
    """The results do not match the plan; no report may be issued."""


def summarise(
    units: list[Unit],
    results: list[CheckResult],
    *,
    snapshot_digest: str,
    schema_version: str,
    bundle_versions: dict[str, str],
    engine_version: str = ENGINE_VERSION,
) -> dict:
    """Aggregate unit results into the audit report baseline."""
    if not units:
        raise AuditReportError("check plan is empty; nothing was audited")

    by_id = {result.check_id: result for result in results}
    if len(by_id) != len(results):
        duplicates = sorted(
            {result.check_id for result in results if sum(1 for r in results if r.check_id == result.check_id) > 1}
        )
        raise AuditReportError(f"duplicate results for planned checks: {duplicates}")
    unknown_ids = sorted(set(by_id) - {unit.check_id for unit in units})
    if unknown_ids:
        raise AuditReportError(f"results for unplanned checks: {unknown_ids}")
    missing_ids = [unit.check_id for unit in units if unit.check_id not in by_id]
    if missing_ids:
        # A unit that produced no result must be reported, not dropped.
        raise AuditReportError(f"checks produced no result: {missing_ids}")

    counts = {status: 0 for status in UNIT_STATUSES}
    reasons: set[str] = set()
    for unit in units:
        result = by_id[unit.check_id]
        counts[result.status] += 1
        if result.reason_code:
            reasons.add(result.reason_code)

    if sum(counts.values()) != len(units):
        raise AuditReportError(
            f"coverage is not conserved: {sum(counts.values())} counted vs {len(units)} planned"
        )

    settled = all(counts[status] == 0 for status in UNIT_STATUSES if status not in SETTLED_STATUSES)
    completion = COMPLETE if settled else PARTIAL

    assessed = counts[PASS] + counts[FINDING]
    coverage = {
        "assessed": assessed,
        "not_applicable": counts[NOT_APPLICABLE],
        "unsettled": counts[NEEDS_INPUT] + counts[UNABLE_TO_ASSESS] + counts[FAILED],
        "ratio": round(assessed / len(units), 3),
    }

    if counts[FINDING]:
        outcome = OUTCOME_FINDINGS
    elif counts[NEEDS_INPUT]:
        outcome = OUTCOME_NEEDS_INPUT
    elif counts[UNABLE_TO_ASSESS] or counts[FAILED]:
        # pass + failed is never "no findings".
        outcome = OUTCOME_UNABLE
    elif counts[PASS]:
        outcome = OUTCOME_NONE
    else:
        outcome = OUTCOME_UNABLE
        reasons.add("no_applicable_checks")

    return {
        "planned": len(units),
        "counts": counts,
        "coverage": coverage,
        "completion": completion,
        "outcome": outcome,
        "freshness": CURRENT,
        "freshness_reasons": [],
        "reasons": sorted(reasons),
        "snapshot_digest": snapshot_digest,
        "schema_version": schema_version,
        "bundle_versions": dict(bundle_versions),
        "engine_version": engine_version,
    }


def mark_stale(report: dict, current_digest: str) -> dict:
    """Return a copy of the report marked stale when the snapshot has moved on.

    Findings stay attached to the snapshot they were produced from; nothing is re-pointed at newer text.
    """
    if report.get("snapshot_digest") == current_digest:
        return report
    stale = dict(report)
    stale["freshness"] = STALE
    stale["freshness_reasons"] = sorted({*report.get("freshness_reasons", []), "snapshot_changed"})
    return stale


def findings_of(results: list[CheckResult]) -> list[dict]:
    """Findings in plan order, for the projection step."""
    return [result.finding for result in results if result.status == FINDING and result.finding]