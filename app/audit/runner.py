"""Run one standards audit over a state dict, without the graph.

This is the glue the acceptance tasks exercise: bind → plan → evaluate (schema, rules, evidence) →
summarise. The node layer (task 6.1) will call exactly this once the frozen-file sign-off lands.
"""

from __future__ import annotations

from app.audit.bind import ABSENT, AuditValue, bind_fields
from app.audit.evidence import evaluate_all as evaluate_evidence
from app.audit.planner import build_plan, units_by_family
from app.audit.project import enforce_anchor, enforce_method_contract, finding_of, known_fields
from app.audit.report import OUTCOME_UNABLE, PARTIAL, mark_stale, summarise
from app.rules.bundles import bundle_versions, find_conflicts, load_bundles, validate_against_schema
from app.rules.engine import evaluate_rule, evaluate_schema_check
from app.rules.schema import SchemaBundle, load_schema
from app.rules.types import ENGINE_VERSION, FINDING, CheckResult


class AuditRunError(RuntimeError):
    """The audit cannot be produced at all (no schema, no bundle, unusable plan)."""


def audit_state(
    state: dict,
    *,
    snapshot_digest: str,
    schema: SchemaBundle | None = None,
    bundles=None,
    current_digest: str | None = None,
) -> dict:
    """Audit `state` and return `{"report", "results", "findings", "units", "conflicts"}`.

    `snapshot_digest` is required: a report that cannot name the snapshot it audited can never be
    judged stale, and a gate on such a report would be permanently unsure.
    """
    if not snapshot_digest:
        raise AuditRunError("snapshot_digest is required; the report must name the snapshot it audited")
    schema = schema or load_schema()
    bundles = list(bundles) if bundles is not None else load_bundles()
    # A rule that cannot be evaluated against this schema is a publish-time defect, not a document defect.
    for bundle in bundles:
        validate_against_schema(bundle, schema)
    units = build_plan(schema, bundles)
    conflicts = find_conflicts(bundles)

    values = bind_fields(state.get("fields"))
    context = {"schema": schema}
    rules = {
        f"RULE:{rule['rule_id']}@{rule['version']}": rule for bundle in bundles for rule in bundle.rules
    }

    results: list[CheckResult] = []
    for unit in units_by_family(units, "schema"):
        field = schema.fields[unit.field_id]
        bound = values.get(unit.field_id) or AuditValue(unit.field_id, ABSENT)
        results.append(evaluate_schema_check(unit, field, bound, schema.version))
    for unit in units_by_family(units, "rule"):
        results.append(evaluate_rule(rules[unit.check_id], values, context))
    results.extend(evaluate_evidence(units_by_family(units, "evidence"), state))

    # Two contract guards the report must never skip: an anchor that does not resolve, and a model
    # opinion that claims the power to hard-block (4.2 / 4.3).
    known = known_fields(schema, state)
    by_id = {unit.check_id: unit for unit in units}
    results = [
        enforce_anchor(enforce_method_contract(result, by_id[result.check_id]), known)
        for result in results
    ]

    report = summarise(
        units,
        results,
        snapshot_digest=snapshot_digest,
        schema_version=schema.version,
        bundle_versions=bundle_versions(bundles),
        engine_version=ENGINE_VERSION,
    )

    # The audit's own copy of each finding — this is what the gate reads (`verification.audit`).
    failure = [
        finding_of(result, by_id[result.check_id])
        for result in results
        if result.status == FINDING
    ]
    report["findings"] = [finding for finding in failure if finding]

    if conflicts:
        # Two published rule versions of the same rule: the audit cannot claim a verdict.
        report["outcome"] = OUTCOME_UNABLE
        report["completion"] = PARTIAL
        report["reasons"] = sorted({*report["reasons"], "rule_conflict"})

    if current_digest is not None:
        report = mark_stale(report, current_digest)

    findings = [result.finding for result in results if result.finding]
    return {"report": report, "results": results, "findings": findings, "units": units, "conflicts": conflicts}