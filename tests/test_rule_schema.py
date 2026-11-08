"""Task 1.1 — the field dictionary projected into an audit schema bundle."""

from __future__ import annotations

import pytest

from app.config import FieldsConfigError
from app.rules.schema import SchemaError, build_schema, load_schema


def test_projects_every_field(fields_yaml):
    schema = load_schema()

    assert len(schema.fields) == len(fields_yaml) == 15
    amount = schema.fields["guarantee_amount"]
    assert amount.value_type == "amount"
    assert amount.required is True
    assert amount.max_length == 18
    assert amount.charset_id == "digits_dot"
    assert amount.precision == 2
    assert amount.date_order is None


def test_keeps_date_order_and_length():
    schema = load_schema()

    assert schema.fields["issue_date"].date_order == "DMY"
    assert schema.fields["issue_date"].value_type == "date"
    assert schema.fields["payment_terms"].max_length == 200
    assert schema.fields["currency"].charset_id == "upper_alpha"


def test_version_is_stable_and_content_addressed(fields_yaml):
    first = load_schema()
    second = load_schema()
    assert first.version == second.version

    changed = {key: dict(value) for key, value in fields_yaml.items()}
    changed["guarantee_amount"] = {**changed["guarantee_amount"], "max_length": 12}
    assert build_schema(changed).version != first.version


def test_broken_configuration_raises_instead_of_empty_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_EDIT_FIELDS_YAML", str(tmp_path / "missing.yaml"))

    with pytest.raises(FieldsConfigError):
        load_schema()


def test_empty_dictionary_is_refused():
    with pytest.raises(SchemaError):
        build_schema({})


def test_charset_outside_the_catalogue_is_refused(fields_yaml):
    broken = {key: dict(value) for key, value in fields_yaml.items()}
    broken["currency"] = {**broken["currency"], "charset": "[A-Z]{3}"}

    with pytest.raises(SchemaError, match="approved catalogue"):
        build_schema(broken)


def test_unsupported_type_is_refused(fields_yaml):
    broken = {key: dict(value) for key, value in fields_yaml.items()}
    broken["currency"] = {**broken["currency"], "type": "regex"}

    with pytest.raises(SchemaError, match="unsupported type"):
        build_schema(broken)