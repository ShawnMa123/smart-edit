"""Tasks 11.1-11.5 — template resolution and policy combination."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.audit.resolve import (
    AMBIGUOUS,
    MISSING_PACK,
    NO_TEMPLATE,
    POLICY_CONFLICT,
    conflicted_fields,
    resolve_policy,
    resolve_template,
)
from app.rules.bundles import load_bundle, load_bundles
from app.rules.templates import TemplatePack, load_template, load_templates

PACK_PATH = Path("app/templates/adidas-guarantee.yaml")
BUNDLE_PATH = Path("app/rules/bundles/guarantee.yaml")


def _state(**overrides) -> dict:
    state = {
        "business_type": "guarantee",
        "fields": {
            "beneficiary_name": {"key": "beneficiary_name", "value": "Adidas AG", "status": "extracted"},
            "currency": {"key": "currency", "value": "USD", "status": "extracted"},
        },
        "extra_fields": {},
    }
    state.update(overrides)
    return state


def _pack() -> TemplatePack:
    return load_template(PACK_PATH)


def _write_pack(tmp_path, name: str, **overrides) -> TemplatePack:
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
    return load_template(path)


def test_the_matching_pack_is_resolved_with_its_basis():
    """11.1 One published match wins, and the report can say why."""
    resolution = resolve_template(_state(), load_templates())

    assert resolution.template is not None
    assert resolution.template.template_id == "adidas-guarantee"
    assert resolution.reason is None
    assert resolution.resolved_from == {
        "document_type": "guarantee",
        "counterparty_field": "beneficiary_name",
        "counterparty_value": "Adidas AG",
    }
    assert resolution.candidates == ({"template_id": "adidas-guarantee", "version": "1.0.0"},)


def test_the_counterparty_match_ignores_case_and_padding():
    """11.1 The comparison is the layer's own normalization, not string equality."""
    padded = _state(
        fields={
            "beneficiary_name": {
                "key": "beneficiary_name",
                "value": "  adidas ag ",
                "status": "extracted",
            }
        }
    )

    assert resolve_template(padded, load_templates()).template is not None


def test_the_counterparty_can_come_from_extra_fields():
    """11.1 Normalization may put the counterparty outside the dictionary."""
    state = _state(
        fields={},
        extra_fields={"beneficiary_name": {"key": "beneficiary_name", "value": "Adidas AG"}},
    )

    assert resolve_template(state, load_templates()).template is not None


def test_no_match_is_unable_to_assess_never_a_guess():
    """11.2 Zero candidates explains itself."""
    other = _state(fields={"beneficiary_name": {"value": "Somebody Else", "status": "extracted"}})

    resolution = resolve_template(other, load_templates())

    assert resolution.template is None
    assert resolution.reason == NO_TEMPLATE
    assert resolution.candidates == ()


def test_two_matches_are_ambiguous_and_listed(tmp_path):
    """11.2 Several candidates are never resolved by load order."""
    templates = [_pack(), _write_pack(tmp_path, "adidas-second")]

    resolution = resolve_template(_state(), templates)

    assert resolution.template is None
    assert resolution.reason == AMBIGUOUS
    assert {candidate["template_id"] for candidate in resolution.candidates} == {
        "adidas-guarantee",
        "adidas-second",
    }


def test_a_reference_narrows_but_cannot_override(tmp_path):
    """11.3 A host reference only narrows the candidate set."""
    templates = [_pack(), _write_pack(tmp_path, "adidas-second")]

    narrowed = resolve_template(_state(), templates, reference={"template_id": "adidas-second"})

    assert narrowed.template is not None
    assert narrowed.template.template_id == "adidas-second"
    assert narrowed.reference_ignored is False


def test_an_unpublished_reference_is_ignored_not_honoured(tmp_path):
    """11.3 Naming an unpublished pack neither selects it nor breaks the audit."""
    draft = _write_pack(tmp_path, "adidas-draft", published=False)
    assert draft.published is False

    resolution = resolve_template(
        _state(), load_templates(), reference={"template_id": "adidas-draft"}
    )

    assert resolution.template is not None
    assert resolution.template.published is True
    assert resolution.reference_ignored is True


def test_the_resolved_policy_lists_every_pack():
    """11.4 The report can name the template plus each policy pack version."""
    policy = resolve_policy(_pack(), load_bundles())

    assert [pack.pack_id for pack in policy.packs] == ["guarantee-core"]
    assert policy.packs[0].version == "1.0.0"
    assert policy.packs[0].source == BUNDLE_PATH.name
    assert policy.conflicts == ()
    assert policy.reason_codes == ()


def test_a_template_and_a_pack_disagreeing_about_gating_is_a_conflict():
    """11.5 Third conflict class: the pack gates `currency` only as hard_block, the template as advisory."""
    bundle = load_bundle(BUNDLE_PATH)
    harder = bundle.__class__(
        **{
            **bundle.__dict__,
            "rules": tuple(
                {**rule, "gate_type": "hard_block"}
                if rule.get("field_id") == "currency"
                else rule
                for rule in bundle.rules
            ),
        }
    )

    policy = resolve_policy(_pack(), [harder])

    assert any("currency is gated inconsistently" in conflict for conflict in policy.conflicts)
    assert POLICY_CONFLICT in policy.reason_codes
    assert conflicted_fields(_pack(), policy) == {"currency"}


def test_a_missing_mandatory_pack_is_a_conflict_not_a_pass():
    """11.5 "Pack missing" must never read as "no applicable checks"."""
    policy = resolve_policy(_pack(), [])

    assert any("mandatory policy pack" in conflict for conflict in policy.conflicts)
    assert policy.reason_codes == (MISSING_PACK,)


def test_several_rules_for_one_field_inside_one_pack_are_not_a_conflict():
    """11.5 `guarantee-core` legitimately gates `guarantee_amount` twice."""
    policy = resolve_policy(_pack(), load_bundles())

    assert policy.conflicts == ()