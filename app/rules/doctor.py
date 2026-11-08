"""Rule-pack health check (OPTIMIZATION P3 item 4).

    .venv/bin/python -m app.rules.doctor            # human readable, exit 1 on any problem
    .venv/bin/python -m app.rules.doctor --json     # machine readable (CI)

Answers the four questions a rule owner actually has before publishing:

1. does every rule reference a field that exists, with a comparable literal type?
2. do two published sources disagree with each other (versions, or gate types)?
3. does every rule still demonstrate `pass`, `finding` **and** `needs_input`?
4. what will one audit plan look like (unit count per family)?

Exit code is the gate: `0` healthy, `1` problems found, `2` the packs could not even be loaded.
"""

from __future__ import annotations

import argparse
import json

from app.audit.bind import ABSENT, CONFIRMED, UNCONFIRMED, AuditValue
from app.audit.planner import PlanError, build_plan, units_by_family
from app.audit.resolve import resolve_policy
from app.rules.bundles import BundleError, find_conflicts, load_bundles, validate_against_schema
from app.rules.engine import evaluate_rule
from app.rules.schema import SchemaError, load_schema
from app.rules.templates import (
    TemplateError,
    compile_expectations,
    load_templates,
    merge_schema,
)
from app.rules.types import ENGINE_VERSION

REQUIRED_VECTOR_STATUSES = ("pass", "finding", "needs_input")
_FAILED = "failed"
# A value that is not in any `allowed_values` list, used to prove an expectation *can* fail.
_PROBE_FAILING_VALUE = "ZZ-NOT-ALLOWED"


def _values(fields: dict) -> dict[str, AuditValue]:
    states = {"absent": ABSENT, "confirmed": CONFIRMED, "unconfirmed": UNCONFIRMED}
    return {
        field_id: AuditValue(field_id, states[spec["state"]], spec.get("value"))
        for field_id, spec in fields.items()
    }


def inspect(*, schema=None, bundles=None) -> dict:
    """Collect the health report. Never raises for pack problems; returns them in `problems`."""
    problems: list[str] = []

    try:
        schema = schema if schema is not None else load_schema()
    except SchemaError as exc:
        return {
            "engine_version": ENGINE_VERSION,
            "schema": None,
            "bundles": [],
            "plan": {},
            "vectors": [],
            "problems": [f"schema unusable: {exc}"],
            "healthy": False,
        }

    if bundles is None:
        try:
            bundles = load_bundles()
        except BundleError as exc:
            return {
                "engine_version": ENGINE_VERSION,
                "schema": {"version": schema.version, "fields": len(schema.fields)},
                "bundles": [],
                "plan": {},
                "vectors": [],
                "problems": [f"bundle could not be loaded: {exc}"],
                "healthy": False,
            }
    bundles = list(bundles)

    if not bundles:
        problems.append("no published bundle applies; an audit would refuse to run")

    for bundle in bundles:
        try:
            validate_against_schema(bundle, schema)
        except BundleError as exc:
            problems.append(str(exc))

    conflicts = find_conflicts(bundles)
    problems.extend(f"conflict: {conflict}" for conflict in conflicts)

    vectors: list[dict] = []
    for bundle in bundles:
        for rule in bundle.rules:
            demonstrated = []
            for vector in rule.get("test_vectors") or []:
                status = evaluate_rule(rule, _values(vector["fields"]), {"schema": schema}).status
                demonstrated.append(status)
                if status != vector["expect"]:
                    problems.append(
                        f"{rule['rule_id']}/{vector['name']}: expected {vector['expect']}, got {status}"
                    )
            if _FAILED in demonstrated:
                problems.append(f"{rule['rule_id']} fails on its own vectors")
            missing = [status for status in REQUIRED_VECTOR_STATUSES if status not in demonstrated]
            if missing:
                problems.append(f"{rule['rule_id']} has no vector producing {missing}")
            vectors.append(
                {
                    "rule_id": rule["rule_id"],
                    "version": rule["version"],
                    "demonstrated": sorted(set(demonstrated)),
                    "vectors": len(demonstrated),
                }
            )

    plan: dict = {}
    if bundles:
        try:
            units = build_plan(schema, bundles)
        except PlanError as exc:
            problems.append(f"plan cannot be built: {exc}")
        else:
            plan = {
                "planned": len(units),
                "schema": len(units_by_family(units, "schema")),
                "rule": len(units_by_family(units, "rule")),
                "evidence": len(units_by_family(units, "evidence")),
                "template": len(units_by_family(units, "template")),
            }

    templates = inspect_templates(schema, bundles, problems)

    return {
        "engine_version": ENGINE_VERSION,
        "schema": {"version": schema.version, "fields": len(schema.fields)},
        "bundles": [
            {
                "id": bundle.bundle_id,
                "version": bundle.version,
                "published": bundle.published,
                "sha256": bundle.content_sha256,
                "rules": len(bundle.rules),
            }
            for bundle in bundles
        ],
        "templates": templates,
        "vectors": vectors,
        "plan": plan,
        "problems": problems,
        "healthy": not problems,
    }


def _demonstrable_states(rule: dict, expectation, schema) -> set[str]:
    """Prove an expectation can produce pass, finding **and** needs_input (the rule-vector gate, compiled).

    A template whose expectation can only ever pass is a green light with nothing behind it, so the same
    bar the rule bundles meet applies here.
    """
    context = {"schema": schema}
    condition = expectation.required_when
    base: dict[str, AuditValue] = {}
    if condition:
        base[str(condition["field_id"])] = AuditValue(
            str(condition["field_id"]), CONFIRMED, str(condition.get("equals"))
        )
    passing_value = expectation.allowed_values[0] if expectation.allowed_values else "probe-value"
    probes = [
        {**base, expectation.field_id: AuditValue(expectation.field_id, CONFIRMED, passing_value)},
        {
            **base,
            expectation.field_id: AuditValue(expectation.field_id, CONFIRMED, _PROBE_FAILING_VALUE),
        },
        {**base, expectation.field_id: AuditValue(expectation.field_id, UNCONFIRMED, passing_value)},
        # Absence is the fourth probe: a *required* expectation can only show a finding this way
        # (`exists` on an absent field), and `allowed_values` simply reports "unknown" for it.
        {**base, expectation.field_id: AuditValue(expectation.field_id, ABSENT)},
    ]
    return {evaluate_rule(rule, probe, context).status for probe in probes}


def inspect_templates(schema, bundles: list, problems: list[str]) -> list[dict]:
    """Templates: field evaluability, clause locatability, demonstrable states, conflicts (task 14.1)."""
    try:
        packs = load_templates()
    except TemplateError as exc:
        problems.append(f"template could not be loaded: {exc}")
        return []

    entries: list[dict] = []
    for pack in packs:
        entry: dict = {
            "template_id": pack.template_id,
            "version": pack.version,
            "published": pack.published,
            "synthetic": pack.synthetic,
            "sha256": pack.content_sha256,
            "fields": len(pack.fields),
            "clauses": len(pack.clauses),
            "declarations": len(pack.declarations),
            "states": {},
            "conflicts": 0,
            "plan": 0,
        }
        try:
            effective = merge_schema(schema, [pack])
            rules = compile_expectations(pack, effective)
        except TemplateError as exc:
            problems.append(str(exc))
            entries.append(entry)
            continue

        for rule, expectation in zip(rules, pack.fields):
            states = _demonstrable_states(rule, expectation, effective)
            entry["states"][expectation.field_id] = sorted(states)
            missing = [state for state in REQUIRED_VECTOR_STATUSES if state not in states]
            if missing:
                problems.append(
                    f"{pack.template_id}/{expectation.field_id}: no probe producing {missing}"
                )

        if pack.clauses and not pack.body:
            problems.append(
                f"{pack.template_id}: declares clauses but no `body` to verify them against"
            )
        for clause in pack.clauses:
            if pack.body is None:
                break
            from app.parsing.normalize import normalize_ws

            if normalize_ws(clause.text) not in normalize_ws(pack.body):
                problems.append(
                    f"{pack.template_id}/{clause.clause_id}: text is not locatable in the template body"
                )

        policy = resolve_policy(pack, bundles)
        entry["conflicts"] = len(policy.conflicts)
        problems.extend(f"{pack.template_id}: conflict: {conflict}" for conflict in policy.conflicts)

        try:
            entry["plan"] = len(build_plan(effective, bundles, templates=[pack]))
        except PlanError as exc:
            problems.append(f"{pack.template_id}: plan cannot be built: {exc}")
        entries.append(entry)
    return entries


def render(report: dict) -> str:
    lines = [f"Rule-pack doctor · engine {report['engine_version']}"]
    schema = report.get("schema")
    if schema:
        lines.append(f"  schema {schema['version']} ({schema['fields']} fields)")
    for bundle in report["bundles"]:
        lines.append(
            f"  bundle {bundle['id']} v{bundle['version']} "
            f"published={bundle['published']} rules={bundle['rules']} sha256={bundle['sha256']}"
        )
    for template in report.get("templates") or []:
        lines.append(
            f"  template {template['template_id']} v{template['version']} "
            f"published={template['published']} synthetic={template['synthetic']} "
            f"sha256={template['sha256']} "
            f"fields={template['fields']} clauses={template['clauses']} "
            f"declarations={template['declarations']} plan={template['plan']} "
            f"conflicts={template['conflicts']}"
        )
        for field_id, states in (template.get("states") or {}).items():
            lines.append(f"    field {field_id:<24} -> {', '.join(states) or '—'}")
    if report["plan"]:
        plan = report["plan"]
        lines.append(
            f"  plan: {plan['planned']} units "
            f"(schema {plan['schema']} · rules {plan['rule']} · evidence {plan['evidence']} · "
            f"template {plan.get('template', 0)})"
        )
    if report["vectors"]:
        lines.append("  vectors:")
        for entry in report["vectors"]:
            lines.append(
                f"    {entry['rule_id']:<28} v{entry['version']:<3} "
                f"{entry['vectors']} vectors -> {', '.join(entry['demonstrated']) or '—'}"
            )

    lines.append("")
    if report["healthy"]:
        lines.append("OK: no problems found")
    else:
        lines.append(f"PROBLEMS ({len(report['problems'])}):")
        lines.extend(f"  - {problem}" for problem in report["problems"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the published rule packs.")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    report = inspect()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    if report["healthy"]:
        return 0
    return 1 if report["bundles"] else 2


if __name__ == "__main__":
    raise SystemExit(main())