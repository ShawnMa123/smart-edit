"""Tasks 3.1 / 3.2 — the check plan and the coverage summary."""

from __future__ import annotations

import pytest

from app.audit.planner import PlanError, build_plan, evidence_units, schema_units
from app.rules.bundles import load_bundles
from app.rules.schema import load_schema
from app.rules.types import Unit


def _bundles():
    return load_bundles()


def test_plan_covers_every_schema_field(fields_yaml):
    schema = load_schema()
    units = build_plan(schema, _bundles())

    type_units = {unit.check_id for unit in units if unit.check_id.endswith(":type")}
    assert type_units == {f"SCHEMA:{field}:type" for field in fields_yaml}

    required_units = {unit.check_id for unit in units if unit.check_id.endswith(":required")}
    assert required_units == {
        f"SCHEMA:{key}:required" for key, fdef in fields_yaml.items() if fdef["required"]
    }


def test_optional_constraints_only_emit_units_when_declared(fields_yaml):
    schema = load_schema()
    units = build_plan(schema, _bundles())
    charset_units = {unit.check_id for unit in units if unit.check_id.endswith(":charset")}

    assert charset_units == {
        f"SCHEMA:{key}:charset" for key, fdef in fields_yaml.items() if fdef.get("charset")
    }
    assert "SCHEMA:applicant_name:charset" not in charset_units


def test_rule_and_evidence_units_are_planned():
    units = build_plan(load_schema(), _bundles())
    rule_ids = {unit.check_id for unit in units if unit.family == "rule"}
    evidence_ids = {unit.check_id for unit in units if unit.family == "evidence"}

    assert "RULE:GR-AMOUNT-POSITIVE@1" in rule_ids
    assert "EVIDENCE:trail_overreach" in evidence_ids
    assert len(evidence_ids) == len(evidence_units())


def test_plan_is_deterministic_and_unique():
    schema = load_schema()
    first = [unit.check_id for unit in build_plan(schema, _bundles())]
    second = [unit.check_id for unit in build_plan(schema, _bundles())]

    assert first == second
    assert len(first) == len(set(first))


def test_empty_bundle_set_is_a_configuration_error():
    with pytest.raises(PlanError, match="no published rule bundle"):
        build_plan(load_schema(), [])


def test_duplicate_check_ids_are_refused():
    schema = load_schema()
    duplicated = Unit(check_id="SCHEMA:guarantee_amount:type", family="schema")
    # A plan built from units that already collide must fail loudly, not silently de-duplicate.
    from app.audit import planner as planner_module

    original = planner_module.schema_units
    try:
        planner_module.schema_units = lambda _schema: [duplicated, duplicated]
        with pytest.raises(PlanError, match="duplicate check id"):
            build_plan(schema, _bundles())
    finally:
        planner_module.schema_units = original


def test_schema_units_mark_required_fields():
    units = {unit.check_id: unit for unit in schema_units(load_schema())}

    assert units["SCHEMA:guarantee_amount:required"].required is True
    assert units["SCHEMA:guarantee_type:type"].required is False