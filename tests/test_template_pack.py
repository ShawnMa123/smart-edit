"""Tasks 10.1-10.4 — template packs: loading, effective schema, DSL compilation, the shipped pack."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.rules.bundles import load_bundles, validate_against_schema
from app.rules.schema import load_schema
from app.rules.templates import (
    TEMPLATE_DIR,
    TemplateError,
    compile_expectations,
    load_template,
    load_templates,
    merge_schema,
)

PACK_PATH = Path("app/templates/adidas-guarantee.yaml")


def _write_pack(tmp_path, name: str, **overrides) -> Path:
    payload = {
        "template_id": name,
        "version": "1.0.0",
        "published": True,
        "document_types": ["guarantee"],
        "counterparty": {"name": "Adidas AG"},
        "fields": [{"key": "currency", "allowed_values": ["USD"], "gate_type": "hard_block"}],
    }
    payload.update(overrides)
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _pack():
    return load_template(PACK_PATH)


def test_the_shipped_pack_loads_with_a_stable_digest():
    """10.1 A published pack loads, is marked synthetic, and hashes the same way twice."""
    pack = _pack()

    assert pack.template_id == "adidas-guarantee"
    assert pack.version == "1.0.0"
    assert pack.published is True
    assert pack.synthetic is True, "a demo pack must never pass as a real customer template"
    assert pack.document_types == ("guarantee",)
    assert pack.counterparty_name == "Adidas AG"
    assert pack.counterparty_field == "beneficiary_name"
    assert len(pack.content_sha256) == 12
    assert pack.content_sha256 == load_template(PACK_PATH).content_sha256
    assert pack.body and "laws of England and Wales" in pack.body


def test_unpublished_packs_are_skipped(tmp_path):
    """10.1 Only published versions reach the audit."""
    _write_pack(tmp_path, "draft", published=False)
    _write_pack(tmp_path, "live")

    assert [pack.template_id for pack in load_templates(tmp_path)] == ["live"]
    assert len(load_templates(tmp_path, include_unpublished=True)) == 2


def test_a_malformed_pack_is_refused(tmp_path):
    """10.1 Missing keys and unknown clause requirements fail at load time."""
    missing = tmp_path / "nopublished.yaml"
    missing.write_text(
        yaml.safe_dump(
            {
                "template_id": "nopublished",
                "version": "1.0.0",
                "fields": [{"key": "currency", "allowed_values": ["USD"]}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="missing published"):
        load_template(missing)
    with pytest.raises(TemplateError, match="requirement"):
        load_template(
            _write_pack(
                tmp_path,
                "badclause",
                clauses=[{"clause_id": "c1", "requirement": "vibes", "text": "x"}],
            )
        )


def test_a_pack_without_expectations_is_refused(tmp_path):
    """10.1 An empty pack would audit nothing and read as clean."""
    path = _write_pack(tmp_path, "empty", fields=[], clauses=[], internal_policy=[])

    with pytest.raises(TemplateError, match="no expectation"):
        load_template(path)


def test_template_fields_join_the_effective_schema(tmp_path):
    """10.2 `origin_country` is not in fields.yaml, so the template declares its type."""
    base = load_schema()
    merged = merge_schema(base, [_pack()])

    assert "origin_country" not in base.fields
    assert merged.fields["origin_country"].value_type == "country"
    assert merged.fields["currency"].value_type == base.fields["currency"].value_type
    assert merged.version == base.version, "the dictionary version stays the schema version"


def test_a_contradicting_field_type_is_a_load_time_error(tmp_path):
    """10.2 The loader never picks a winner between the dictionary and the template."""
    base = load_schema()
    conflicting = load_template(
        _write_pack(tmp_path, "conflict", fields=[{"key": "currency", "type": "string",
                                                   "allowed_values": ["USD"]}])
    )

    with pytest.raises(TemplateError, match="contradicts"):
        merge_schema(base, [conflicting])


def test_a_template_field_without_a_type_is_refused(tmp_path):
    """10.2 An unknown field with no declared type cannot be evaluated."""
    base = load_schema()
    untyped = load_template(
        _write_pack(tmp_path, "untyped", fields=[{"key": "origin_country", "allowed_values": ["VN"]}])
    )

    with pytest.raises(TemplateError, match="does not declare its type"):
        merge_schema(base, [untyped])
def test_expectations_compile_onto_the_closed_op_set():
    """10.3 Every expectation becomes a rule the existing engine and validator accept."""
    schema = merge_schema(load_schema(), [_pack()])
    rules = {rule["rule_id"]: rule for rule in compile_expectations(_pack(), schema)}

    currency = rules["TEMPLATE:adidas-guarantee:currency"]
    assert currency["expression"] == {
        "op": "compare",
        "left": {"kind": "field", "field_id": "currency"},
        "comparator": "eq",
        "right": {"kind": "literal", "value_type": "string", "value": "USD"},
    }
    assert currency["gate_type"] == "advisory", "the bank pack already gates `currency`; no re-gating"
    assert currency["target_operations"] == []

    origin = rules["TEMPLATE:adidas-guarantee:origin_country"]
    assert origin["expression"]["op"] == "any"
    assert [arg["right"]["value"] for arg in origin["expression"]["args"]] == ["VN", "TH"]
    assert origin["gate_type"] == "hard_block"
    assert "start_approval" in origin["target_operations"]

    conditional = rules["TEMPLATE:adidas-guarantee:guarantee_amount"]
    assert conditional["applicability"]["left"]["field_id"] == "currency"
    assert conditional["applicability"]["right"]["value"] == "USD"
    assert "expression" in conditional, "the checked field lives in expression, never in required_facts"


def test_compiled_rules_are_evaluable_by_the_engine():
    """10.3 The compiled rule is indistinguishable from a hand-written one."""
    from app.audit.bind import AuditValue, CONFIRMED, UNCONFIRMED
    from app.rules.engine import evaluate_rule
    from app.rules.types import FINDING, NEEDS_INPUT, PASS

    schema = merge_schema(load_schema(), [_pack()])
    rules = {rule["rule_id"]: rule for rule in compile_expectations(_pack(), schema)}
    currency = rules["TEMPLATE:adidas-guarantee:currency"]
    context = {"schema": schema}

    usd = evaluate_rule(currency, {"currency": AuditValue("currency", CONFIRMED, "USD")}, context)
    eur = evaluate_rule(currency, {"currency": AuditValue("currency", CONFIRMED, "EUR")}, context)
    guess = evaluate_rule(currency, {"currency": AuditValue("currency", UNCONFIRMED, "EUR")}, context)

    assert usd.status == PASS
    assert eur.status == FINDING
    assert eur.finding["gate_type"] == "advisory"
    assert guess.status == NEEDS_INPUT


def test_compiled_rules_pass_the_schema_validator():
    """10.3 `validate_against_schema()` accepts the compiled rules, so templates cannot drift."""
    from app.rules.bundles import RuleBundle

    schema = merge_schema(load_schema(), [_pack()])
    bundle = RuleBundle(
        bundle_id="adidas-guarantee",
        version="1.0.0",
        published=True,
        content_sha256="x",
        document_types=("guarantee",),
        rules=tuple(compile_expectations(_pack(), schema)),
    )

    validate_against_schema(bundle, schema)  # no raise


def test_allowed_values_on_a_non_text_field_is_refused(tmp_path):
    """10.3 Enumeration compares text; an amount expectation needs typed literals (not this build)."""
    pack = load_template(
        _write_pack(
            tmp_path, "amounts", fields=[{"key": "guarantee_amount", "allowed_values": ["500000"]}]
        )
    )

    with pytest.raises(TemplateError, match="allowed_values"):
        compile_expectations(pack, load_schema())


def test_the_shipped_pack_is_consistent_with_the_published_bundle():
    """10.4 The pack names a policy pack that exists, and its controlled text lives in its body."""
    pack = _pack()
    bundle_ids = {bundle.bundle_id for bundle in load_bundles()}

    assert set(pack.policy_packs) <= bundle_ids
    schema = merge_schema(load_schema(), [pack])
    assert len(compile_expectations(pack, schema)) == 3
    for clause in pack.clauses:
        assert clause.text in (pack.body or ""), "doctor verifies controlled text against the body"
    assert TEMPLATE_DIR.is_dir()
