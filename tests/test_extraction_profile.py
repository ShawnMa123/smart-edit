"""Extraction profile loading (change: config-driven-audit-extraction, tasks 1.1-1.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from app.parsing.extraction_profile import (
    ExtractionProfile,
    ProfileError,
    load_profile,
    load_profile_by_id,
    resolve_profile,
    validate_profile,
)
from app.rules.templates import load_template
from app.runtime import resolve_extraction_profile

ADIDAS_TEMPLATE = Path("app/templates/adidas-guarantee.yaml")

VALID = {
    "profile_id": "demo",
    "version": "1.0.0",
    "published": True,
    "document_types": ["guarantee"],
    "fields": {
        "guarantee_amount": {
            "labels": ["保函金额", "AMOUNT"],
            "value_kind": "amount",
            "search": "same_block",
            "max_chars": 40,
            "confidence": 0.9,
        }
    },
}


def _write(tmp_path, payload, name="demo.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_shipped_profile_loads_with_a_stable_identity(fields_yaml):
    profile = load_profile_by_id("guarantee-default", fields_config=fields_yaml, document_type="guarantee")

    assert isinstance(profile, ExtractionProfile)
    assert profile.profile_id == "guarantee-default"
    assert profile.version == "1.0.0"
    assert len(profile.content_sha256) == 12
    assert profile.identity["content_sha256"] == profile.content_sha256
    assert set(profile.fields) == {
        "guarantee_amount",
        "currency",
        "issue_date",
        "expiry_date",
        "governing_rules",
        "payment_terms",
    }
    assert profile.fields["guarantee_amount"].value_kind == "amount"
    assert profile.fields["payment_terms"].search == "same_or_next_block"


def test_valid_profile_validates_without_filesystem(tmp_path, fields_yaml):
    profile = validate_profile(VALID, fields_config=fields_yaml)

    assert profile.fields["guarantee_amount"].labels == ("保函金额", "AMOUNT")
    assert profile.llm_fallback == {"enabled": False}


def test_unknown_field_key_is_rejected(fields_yaml):
    payload = {**VALID, "fields": {"not_a_field": VALID["fields"]["guarantee_amount"]}}

    with pytest.raises(ProfileError, match="unknown field key"):
        validate_profile(payload, fields_config=fields_yaml)


def test_unsupported_value_kind_is_rejected(fields_yaml):
    field = {**VALID["fields"]["guarantee_amount"], "value_kind": "regex"}

    with pytest.raises(ProfileError, match="value_kind"):
        validate_profile({**VALID, "fields": {"guarantee_amount": field}}, fields_config=fields_yaml)


def test_inline_pattern_or_script_key_is_rejected(fields_yaml):
    field = {**VALID["fields"]["guarantee_amount"], "pattern": r"\d+"}

    with pytest.raises(ProfileError, match="unsupported key"):
        validate_profile({**VALID, "fields": {"guarantee_amount": field}}, fields_config=fields_yaml)


def test_invalid_json_is_rejected(tmp_path, fields_yaml):
    path = tmp_path / "demo.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ProfileError, match="failed to parse"):
        load_profile(path, fields_config=fields_yaml)


def test_unpublished_profile_is_refused(tmp_path, fields_yaml):
    path = _write(tmp_path, {**VALID, "published": False})

    with pytest.raises(ProfileError, match="not published"):
        load_profile(path, fields_config=fields_yaml)


def test_document_type_mismatch_is_refused(tmp_path, fields_yaml):
    path = _write(tmp_path, {**VALID, "document_types": ["invoice"]})

    with pytest.raises(ProfileError, match="does not apply to document type"):
        load_profile(path, fields_config=fields_yaml, document_type="guarantee")


@dataclass(frozen=True)
class _Template:
    extraction_profile: str | None


def test_resolution_order_request_over_template_then_none(tmp_path, fields_yaml):
    path = _write(tmp_path, VALID)
    second = _write(
        tmp_path,
        {**VALID, "profile_id": "second", "fields": {"currency": {
            "labels": ["币种"], "value_kind": "currency", "search": "same_block",
            "max_chars": 8, "confidence": 0.9,
        }}},
        name="second.json",
    )
    assert path and second

    requested = resolve_profile(
        requested="second",
        template=_Template("demo"),
        directory=tmp_path,
        fields_config=fields_yaml,
        document_type="guarantee",
    )
    from_template = resolve_profile(
        template=_Template("demo"),
        directory=tmp_path,
        fields_config=fields_yaml,
        document_type="guarantee",
    )
    none = resolve_profile(directory=tmp_path, fields_config=fields_yaml, document_type="guarantee")

    assert requested is not None and requested.profile_id == "second"
    assert from_template is not None and from_template.profile_id == "demo"
    assert none is None


def test_the_shipped_template_declares_its_extraction_profile():
    """Task 4.2: a published template can name the profile its documents are read with."""
    pack = load_template(ADIDAS_TEMPLATE)

    assert pack.extraction_profile == "guarantee-default"


def test_resolve_extraction_profile_request_template_and_none(tmp_path, fields_yaml, monkeypatch):
    """Task 4.2: `?profile=` > template `extraction_profile` > no profile."""
    _write(tmp_path, VALID, name="demo.json")
    _write(
        tmp_path,
        {**VALID, "profile_id": "second", "fields": {"currency": {
            "labels": ["币种"], "value_kind": "currency", "search": "same_block",
            "max_chars": 8, "confidence": 0.9,
        }}},
        name="second.json",
    )
    monkeypatch.setenv("SMART_EDIT_EXTRACTION_PROFILES", str(tmp_path))
    template = replace(load_template(ADIDAS_TEMPLATE), extraction_profile="demo")

    requested = resolve_extraction_profile(
        {"business_type": "guarantee"},
        requested="second",
        template_id="adidas-guarantee",
        templates=[template],
        fields_config=fields_yaml,
    )
    from_template = resolve_extraction_profile(
        {"business_type": "guarantee"},
        template_id="adidas-guarantee",
        templates=[template],
        fields_config=fields_yaml,
    )
    none = resolve_extraction_profile(
        {"business_type": "guarantee"}, templates=[template], fields_config=fields_yaml
    )

    assert requested is not None and requested.profile_id == "second"
    assert from_template is not None and from_template.profile_id == "demo"
    assert none is None


def test_resolve_extraction_profile_refuses_an_unknown_profile(tmp_path, fields_yaml, monkeypatch):
    """An explicit profile never falls back to the fixture path (task 4.2)."""
    monkeypatch.setenv("SMART_EDIT_EXTRACTION_PROFILES", str(tmp_path))

    with pytest.raises(ProfileError, match="missing or unreadable"):
        resolve_extraction_profile(
            {"business_type": "guarantee"},
            requested="missing",
            templates=[],
            fields_config=fields_yaml,
        )


def test_resolve_extraction_profile_refuses_a_type_mismatch(fields_yaml, monkeypatch):
    monkeypatch.delenv("SMART_EDIT_EXTRACTION_PROFILES", raising=False)

    with pytest.raises(ProfileError, match="does not apply to document type"):
        resolve_extraction_profile(
            {"business_type": "invoice"},
            requested="guarantee-default",
            templates=[],
            fields_config=fields_yaml,
        )
