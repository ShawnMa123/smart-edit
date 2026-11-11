"""Run one standards audit over a state dict, without the graph.

This is the glue the acceptance tasks exercise: bind → plan → evaluate (schema, rules, evidence) →
summarise. The node layer (task 6.1) will call exactly this once the frozen-file sign-off lands.
"""

from __future__ import annotations

from app.audit.bind import ABSENT, AuditValue, bind_fields
from app.audit.clauses import evaluate_all as evaluate_clauses
from app.audit.evidence import evaluate_all as evaluate_evidence
from app.audit.planner import TEMPLATE_RESOLUTION_UNIT, build_plan, units_by_family
from app.audit.project import enforce_anchor, enforce_method_contract, finding_of, known_fields
from app.audit.report import OUTCOME_UNABLE, PARTIAL, mark_stale, summarise
from app.audit.resolve import (
    NOT_REQUESTED,
    Resolution,
    conflicted_fields,
    resolve_policy,
    resolve_template,
    template_baseline,
)
from app.rules.bundles import bundle_versions, find_conflicts, load_bundles, validate_against_schema
from app.rules.engine import evaluate_rule, evaluate_schema_check
from app.rules.schema import SchemaBundle, load_schema
from app.rules.templates import compile_expectations, load_templates, merge_schema
from app.rules.types import ENGINE_VERSION, FAILED, FINDING, UNABLE_TO_ASSESS, CheckResult


class AuditRunError(RuntimeError):
    """The audit cannot be produced at all (no schema, no bundle, unusable plan)."""


def _guarded(unit, evaluate) -> CheckResult:
    """One crashing evaluator must fail its own unit, not abort the whole audit."""
    try:
        return evaluate()
    except Exception as exc:  # noqa: BLE001 - deliberately isolates third-party/rule failures
        return CheckResult(
            unit.check_id,
            FAILED,
            reason_code=f"checker_crashed: {type(exc).__name__}",
        )


def audit_state(
    state: dict,
    *,
    snapshot_digest: str,
    schema: SchemaBundle | None = None,
    bundles=None,
    templates=None,
    template_reference: dict | None = None,
    current_digest: str | None = None,
) -> dict:
    """Audit `state` and return `{"report", "results", "findings", "units", "conflicts", "template"}`.

    `snapshot_digest` is required: a report that cannot name the snapshot it audited can never be
    judged stale, and a gate on such a report would be permanently unsure.

    `templates` defaults to the published packs on disk; pass `[]` to audit the rule bundle alone.
    """
    if not snapshot_digest:
        raise AuditRunError("snapshot_digest is required; the report must name the snapshot it audited")
    base_schema = schema or load_schema()
    bundles = list(bundles) if bundles is not None else load_bundles()

    # Template-driven audit is **requested**, never assumed: a document whose customer has no template is
    # still auditable by the base schema and the bank packs (that is the 51-unit baseline). Only when the
    # host asks — `templates=[…]` or a `template_reference` — does a failed resolution become loud.
    requested = templates is not None or template_reference is not None
    packs = list(templates) if templates is not None else (load_templates() if requested else [])
    if requested:
        resolution = resolve_template(state, packs, reference=template_reference)
    else:
        resolution = Resolution(template=None, reason=NOT_REQUESTED, document_type=state.get("business_type"))
    template = resolution.template
    policy = resolve_policy(template, bundles) if template is not None else None
    schema = merge_schema(base_schema, [template]) if template is not None else base_schema

    # A rule that cannot be evaluated against this schema is a publish-time defect, not a document defect.
    for bundle in bundles:
        validate_against_schema(bundle, schema)

    units = build_plan(
        schema,
        bundles,
        templates=[template] if template is not None else (),
        # Only a *requested* template that failed earns a unit of its own; "not requested" adds nothing.
        resolution_reason=resolution.reason if requested else None,
    )
    conflicts = list(find_conflicts(bundles))
    if policy is not None:
        conflicts = list(policy.conflicts)

    values = bind_fields(state.get("fields"))
    values.update(bind_fields(state.get("extra_fields")))
    context = {"schema": schema}
    rules = {
        f"RULE:{rule['rule_id']}@{rule['version']}": rule for bundle in bundles for rule in bundle.rules
    }
    template_rules = (
        {rule["rule_id"]: rule for rule in compile_expectations(template, schema)}
        if template is not None
        else {}
    )
    conflicted = conflicted_fields(template, policy) if (template is not None and policy) else set()

    results: list[CheckResult] = []
    for unit in units_by_family(units, "schema"):
        results.append(
            _guarded(
                unit,
                lambda unit=unit: evaluate_schema_check(
                    unit,
                    schema.fields[unit.field_id],
                    values.get(unit.field_id) or AuditValue(unit.field_id, ABSENT),
                    schema.version,
                ),
            )
        )
    for unit in units_by_family(units, "rule"):
        results.append(
            _guarded(
                unit,
                lambda unit=unit: evaluate_rule(rules[unit.check_id], values, context),
            )
        )
    results.extend(evaluate_evidence(units_by_family(units, "evidence"), state))
    results.extend(
        _evaluate_template_units(
            units_by_family(units, "template"), template, state, values, context, template_rules, conflicted, resolution
        )
    )

    if template is not None and policy is not None and policy.reason_codes:
        # The policy disagrees with itself (or a mandatory pack is missing): the affected expectation
        # could not be trusted, so the report says so at the top instead of quietly averaging it out.
        report_reasons = list(policy.reason_codes)
    else:
        report_reasons = []

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

    # The template baseline (design D20): which template judged this document, and why that one.
    report["template"] = template_baseline(resolution, policy, template)

    # The audit's own copy of each finding — this is what the gate reads (`verification.audit`).
    failure = [
        finding_of(result, by_id[result.check_id])
        for result in results
        if result.status == FINDING
    ]
    report["findings"] = [finding for finding in failure if finding]

    if conflicts:
        # Conflicting sources (two rule versions, or a template vs a policy pack) mean the audit cannot
        # claim a verdict. `rule_conflict` is the umbrella reason the gate blocks on; the specific codes
        # (`policy_conflict`, `missing_policy_pack`) are added alongside so the screen can explain it.
        report["outcome"] = OUTCOME_UNABLE
        report["completion"] = PARTIAL
        report["reasons"] = sorted({*report["reasons"], "rule_conflict", *report_reasons})

    if current_digest is not None:
        report = mark_stale(report, current_digest)

    findings = [result.finding for result in results if result.finding]
    return {
        "report": report,
        "results": results,
        "findings": findings,
        "units": units,
        "conflicts": conflicts,
        "template": report["template"],
    }


def _evaluate_template_units(
    units,
    template,
    state: dict,
    values: dict,
    context: dict,
    template_rules: dict,
    conflicted: set[str],
    resolution,
) -> list[CheckResult]:
    """Field expectations through the engine, clauses/declarations through `clauses.py`.

    When no template resolved there is exactly one unit (`TEMPLATE:resolution`) and it is
    `unable_to_assess`: an empty template slice would otherwise read as "nothing to check, all good".
    """
    if not units:
        return []
    if template is None:
        return [
            CheckResult(
                unit.check_id,
                UNABLE_TO_ASSESS,
                reason_code=resolution.reason or "no_applicable_template",
                detail={"candidates": list(resolution.candidates)},
            )
            for unit in units
        ]

    results: list[CheckResult] = []
    text_units = []
    for unit in units:
        kind = unit.check_id.split(":", 3)[2]
        if kind != "field":
            text_units.append(unit)
            continue
        if unit.field_id in conflicted:
            # The policy disagrees with the template about this field: no verdict is available.
            results.append(
                CheckResult(
                    unit.check_id,
                    UNABLE_TO_ASSESS,
                    reason_code="policy_conflict",
                    detail={"field_id": unit.field_id},
                )
            )
            continue
        rule = template_rules.get((unit.rule_ref or {}).get("rule_id"))
        if rule is None:
            results.append(
                CheckResult(unit.check_id, FAILED, reason_code="missing_template_rule")
            )
            continue
        evaluated = _guarded(
            unit, lambda rule=rule, unit=unit: evaluate_rule(rule, values, context)
        )
        if evaluated.status == FAILED:
            # `_guarded` reports the crash itself; nothing else can be attributed to this unit.
            results.append(evaluated)
            continue
        # `evaluate_rule` names its result after the rule; the plan unit has the finer id, so the
        # coverage accounting stays keyed to what was planned.
        results.append(
            CheckResult(
                unit.check_id,
                evaluated.status,
                reason_code=evaluated.reason_code,
                finding=evaluated.finding,
                detail=evaluated.detail,
            )
        )
    try:
        results.extend(evaluate_clauses(text_units, template, state))
    except Exception as exc:  # noqa: BLE001 - one broken clause unit must not lose the report
        reason = f"checker_crashed: {type(exc).__name__}"
        results.extend(CheckResult(unit.check_id, FAILED, reason_code=reason) for unit in text_units)
    return results