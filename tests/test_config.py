"""Field dictionary and startup validation (tasks 1.x)."""

from __future__ import annotations

import pytest

from app.config import (
    DEFAULT_FIELDS_PATH,
    NORMALIZE_CONSTRAINTS,
    VALIDATE_CONSTRAINTS,
    FieldsConfigError,
    load_fields_config,
    validate_fields_config,
)
from app.nodes.normalize import normalize_node


def test_dictionary_has_12_to_15_guarantee_fields(fields_yaml):
    """1.1 The 12-15 core guarantee fields."""
    assert 12 <= len(fields_yaml) <= 15


def test_every_field_has_required_keys(fields_yaml):
    """1.1 Every field carries key / label / aliases / type / required."""
    for key, fdef in fields_yaml.items():
        assert fdef["key"] == key
        for name in ("label", "aliases", "type", "required"):
            assert name in fdef, f"{key} is missing {name}"
        assert isinstance(fdef["aliases"], list) and fdef["aliases"]


def test_every_constraint_is_assigned_to_a_stage(fields_yaml):
    """1.2 Every constraint declares which `stage` owns it, without crossing the line (1.3 form constraints -> normalize)."""
    for key, fdef in fields_yaml.items():
        stage = fdef["stage"]
        assert set(stage) == {"normalize", "validate"}
        assert set(stage["normalize"]) <= set(NORMALIZE_CONSTRAINTS)
        assert set(stage["validate"]) <= set(VALIDATE_CONSTRAINTS)
        # a constraint declared in stage.normalize must have a real value on the field
        for constraint in stage["normalize"]:
            if constraint == "date_order":
                assert "date_order" in fdef
            else:
                assert fdef.get(constraint) is not None


def test_required_is_always_explicit_bool(fields_yaml):
    """1.5 `required` is always an explicit `true` / `false`."""
    for key, fdef in fields_yaml.items():
        assert isinstance(fdef["required"], bool), f"{key}.required is not an explicit bool"


def test_date_fields_declare_date_order_explicitly(fields_yaml):
    """1.4 Date fields declare `date_order` explicitly (DMY / MDY / null), never omitted."""
    for key, fdef in fields_yaml.items():
        assert "date_order" in fdef, f"{key} is missing date_order"
        if fdef["type"] == "date":
            assert fdef["date_order"] in ("DMY", "MDY", None)
            assert "date_order" in fdef["stage"]["normalize"]
        else:
            assert fdef["date_order"] is None


def test_required_cannot_be_normalize_stage_constraint():
    """1.6 `required` belongs to validate only: A reads it and never blocks, so a wrong owner must fail at startup."""
    broken = {
        "fields": [
            {
                "key": "x",
                "label": "X",
                "aliases": ["X"],
                "type": "string",
                "required": True,
                "date_order": None,
                "stage": {"normalize": ["required"], "validate": []},
                "max_length": 10,
            }
        ]
    }
    with pytest.raises(FieldsConfigError, match="required"):
        validate_fields_config(broken)


def test_missing_required_key_raises():
    broken = {"fields": [{"key": "x", "label": "X", "aliases": ["X"], "type": "string"}]}
    with pytest.raises(FieldsConfigError):
        validate_fields_config(broken)


def test_missing_file_raises_never_empty_dict(tmp_path):
    """1.7 A missing file must raise, **never** return an empty dict and carry on."""
    with pytest.raises(FieldsConfigError, match="missing or unreadable"):
        load_fields_config(tmp_path / "nope.yaml")


def test_empty_file_raises(tmp_path):
    empty = tmp_path / "fields.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(FieldsConfigError, match="is empty"):
        load_fields_config(empty)


def test_unparseable_file_raises(tmp_path):
    bad = tmp_path / "fields.yaml"
    bad.write_text("fields: [unclosed", encoding="utf-8")
    with pytest.raises(FieldsConfigError, match="failed to parse"):
        load_fields_config(bad)


def test_node_marks_three_stages_failed_when_config_broken(tmp_path, monkeypatch):
    """1.7 When config is unusable all three stages are `failed` and the whole run is `fail`."""
    monkeypatch.setenv("SMART_EDIT_FIELDS_YAML", str(tmp_path / "missing.yaml"))
    state = {"docs": [{"file_id": "F-1", "full_text": "x", "blocks": [], "errors": []}], "trail": []}

    update = normalize_node(state)

    assert [report["stage"] for report in update["stages"]] == ["parse", "extract", "normalize"]
    assert all(report["status"] == "failed" for report in update["stages"])
    assert all("fields.yaml unavailable" in report["reason"] for report in update["stages"])
    assert "fields" not in update


def test_no_constraint_is_owned_by_both_stages(fields_yaml):
    """1.6 No constraint may be implemented on both sides (A and B ownership never overlaps)."""
    for key, fdef in fields_yaml.items():
        normalize_stage = set(fdef["stage"]["normalize"])
        validate_stage = set(fdef["stage"]["validate"])
        overlap = normalize_stage & validate_stage
        assert not overlap, f"{key} constraints {overlap} are owned by both A and B"


def test_normalize_and_validate_constraint_vocabularies_do_not_overlap():
    assert not set(NORMALIZE_CONSTRAINTS) & set(VALIDATE_CONSTRAINTS)


def test_default_path_points_at_repo_config():
    assert DEFAULT_FIELDS_PATH.is_file()
    assert DEFAULT_FIELDS_PATH.name == "fields.yaml"