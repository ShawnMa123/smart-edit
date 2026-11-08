"""Build the check plan **before** anything is evaluated (design D6).

The plan is the denominator of every coverage number. If a check is not planned here it can never appear
in a report, so this module is deliberately boring: schema units, rule units, evidence units, deduplicated
and ordered deterministically.
"""

from __future__ import annotations

from app.rules.bundles import RuleBundle
from app.rules.schema import SchemaBundle
from app.rules.types import Unit


class PlanError(ValueError):
    """The check plan cannot be built (duplicate ids, empty plan)."""


EVIDENCE_CHECKS = (
    ("trail_overreach", "operations that rewrite or drop source text"),
    ("provenance", "extracted values must be locatable in their own file"),
    ("finding_anchor", "findings must point at real fields"),
    ("citation_support", "requires agent-regulatory output"),
    ("conclusion_conflict", "requires agent-verify + agent-regulatory output"),
    ("coverage_declaration", "requires agent-regulatory output"),
)


def schema_units(schema: SchemaBundle) -> list[Unit]:
    units: list[Unit] = []
    for field_id, field in schema.fields.items():
        if field.required:
            units.append(Unit(check_id=f"SCHEMA:{field_id}:required", family="schema", field_id=field_id, required=True))
        units.append(
            Unit(check_id=f"SCHEMA:{field_id}:type", family="schema", field_id=field_id, required=field.required)
        )
        if field.max_length is not None:
            units.append(
                Unit(check_id=f"SCHEMA:{field_id}:max_length", family="schema", field_id=field_id, required=field.required)
            )
        if field.charset_id is not None:
            units.append(
                Unit(check_id=f"SCHEMA:{field_id}:charset", family="schema", field_id=field_id, required=field.required)
            )
    return units


def rule_units(bundles: list[RuleBundle]) -> list[Unit]:
    units: list[Unit] = []
    for bundle in bundles:
        for rule in bundle.rules:
            units.append(
                Unit(
                    check_id=f"RULE:{rule['rule_id']}@{rule['version']}",
                    family="rule",
                    rule_ref={"rule_id": rule["rule_id"], "version": rule["version"]},
                    field_id=rule.get("field_id"),
                    required=rule.get("gate_type") == "hard_block",
                    scope_key=bundle.bundle_id,
                )
            )
    return units


def evidence_units() -> list[Unit]:
    return [
        Unit(check_id=f"EVIDENCE:{name}", family="evidence", required=False)
        for name, _purpose in EVIDENCE_CHECKS
    ]


def build_plan(schema: SchemaBundle, bundles: list[RuleBundle], *, include_evidence: bool = True) -> list[Unit]:
    """Return the planned units. Raises when the plan is empty or contains duplicate ids."""
    if not bundles:
        raise PlanError("no published rule bundle applies; refusing to report an empty check plan")

    units = schema_units(schema) + rule_units(bundles) + (evidence_units() if include_evidence else [])
    seen: set[str] = set()
    for unit in units:
        if unit.check_id in seen:
            raise PlanError(f"duplicate check id in plan: {unit.check_id}")
        seen.add(unit.check_id)
    if not units:
        raise PlanError("check plan is empty")
    return units


def units_by_family(units: list[Unit], family: str) -> list[Unit]:
    return [unit for unit in units if unit.family == family]