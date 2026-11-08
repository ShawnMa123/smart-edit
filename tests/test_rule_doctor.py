"""P3 item 4 (`OPTIMIZATION.md`) — the rule-pack doctor, whose *exit code* is the gate.

A rule owner runs `python -m app.rules.doctor` before publishing. It answers four questions in one
command; the exit code is what CI branches on: `0` healthy, `1` problems found, `2` the packs could
not even be loaded. A doctor that exits `0` because it checked nothing would be worse than none.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.rules import doctor
from app.rules.bundles import BundleError, load_bundle
from app.rules.schema import SchemaError, load_schema

BUNDLE_PATH = Path("app/rules/bundles/guarantee.yaml")


def _write_bundle(tmp_path, name: str, rule_overrides: dict | None = None) -> Path:
    """One published bundle with one amount rule that demonstrates pass/finding/needs_input."""
    rule = {
        "rule_id": f"{name.upper()}-1",
        "version": 1,
        "title": "t",
        "severity": "warn",
        "gate_type": "advisory",
        "category": "field",
        "field_id": "guarantee_amount",
        "expression": {
            "op": "compare",
            "left": {"kind": "field", "field_id": "guarantee_amount"},
            "comparator": "gt",
            "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
        },
        "test_vectors": [
            {
                "name": "zero is a finding",
                "fields": {"guarantee_amount": {"state": "confirmed", "value": "0.00"}},
                "expect": "finding",
            },
            {
                "name": "positive passes",
                "fields": {"guarantee_amount": {"state": "confirmed", "value": "1.00"}},
                "expect": "pass",
            },
            {
                "name": "unconfirmed needs input",
                "fields": {"guarantee_amount": {"state": "unconfirmed", "value": "1.00"}},
                "expect": "needs_input",
            },
        ],
    }
    rule.update(rule_overrides or {})

    path = tmp_path / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump({"bundle_id": name, "version": "1.0.0", "published": True, "rules": [rule]}),
        encoding="utf-8",
    )
    return path


def test_the_shipped_pack_is_healthy():
    report = doctor.inspect()

    assert report["problems"] == []
    assert report["healthy"] is True
    assert report["schema"] == {"version": load_schema().version, "fields": 15}
    assert report["plan"] == {"planned": 51, "schema": 39, "rule": 6, "evidence": 6}
    assert report["bundles"] == [
        {
            "id": "guarantee-core",
            "version": "1.0.0",
            "published": True,
            "sha256": load_bundle(BUNDLE_PATH).content_sha256,
            "rules": 6,
        }
    ]


def test_every_rule_still_demonstrates_pass_finding_and_needs_input():
    report = doctor.inspect()

    assert len(report["vectors"]) == 6
    for entry in report["vectors"]:
        assert entry["vectors"] >= 3
        assert {"pass", "finding", "needs_input"} <= set(entry["demonstrated"])


def test_a_vector_that_disagrees_with_the_engine_is_a_problem(tmp_path):
    """A declared expectation is a promise about the engine; drifting from it must fail the pack."""
    path = _write_bundle(
        tmp_path,
        "liar",
        {
            "test_vectors": [
                {
                    "name": "claims pass",
                    "fields": {"guarantee_amount": {"state": "confirmed", "value": "0.00"}},
                    "expect": "pass",
                }
            ]
        },
    )

    report = doctor.inspect(bundles=[load_bundle(path)])

    assert report["healthy"] is False
    assert any(
        "LIAR-1/claims pass: expected pass, got finding" in problem for problem in report["problems"]
    )


def test_a_rule_without_vectors_is_a_problem(tmp_path):
    path = _write_bundle(tmp_path, "novector", {"test_vectors": []})

    report = doctor.inspect(bundles=[load_bundle(path)])

    assert any("has no vector producing" in problem for problem in report["problems"])


def test_a_rule_referencing_an_unknown_field_is_a_problem(tmp_path):
    """The typo case: otherwise every document silently gets a 'not applicable' unit."""
    path = _write_bundle(
        tmp_path,
        "typo",
        {
            "field_id": "guarantee_ammount",
            "expression": {"op": "exists", "field_id": "guarantee_ammount"},
            "test_vectors": [],
        },
    )

    report = doctor.inspect(bundles=[load_bundle(path)])

    assert any("unknown field" in problem for problem in report["problems"])


def test_two_sources_disagreeing_about_a_rule_are_a_conflict(tmp_path):
    first = load_bundle(_write_bundle(tmp_path, "bank", {"rule_id": "GR-AMOUNT-POSITIVE"}))
    second = load_bundle(
        _write_bundle(tmp_path, "client", {"rule_id": "GR-AMOUNT-POSITIVE", "version": 2})
    )

    report = doctor.inspect(bundles=[first, second])

    assert any(problem.startswith("conflict:") for problem in report["problems"])


def test_no_published_bundle_is_a_problem_and_exits_two(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "load_bundles", lambda *args, **kwargs: [])

    report = doctor.inspect()

    assert report["problems"] == ["no published bundle applies; an audit would refuse to run"]
    assert report["healthy"] is False
    assert report["plan"] == {}
    assert doctor.main([]) == 2
    assert "an audit would refuse to run" in capsys.readouterr().out


def test_an_unreadable_pack_exits_two(monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise BundleError("broken.yaml: missing rules")

    monkeypatch.setattr(doctor, "load_bundles", explode)

    report = doctor.inspect()

    assert report["problems"] == ["bundle could not be loaded: broken.yaml: missing rules"]
    assert doctor.main([]) == 2
    assert "PROBLEMS (1)" in capsys.readouterr().out


def test_an_unusable_schema_is_reported(monkeypatch):
    def explode():
        raise SchemaError("fields.yaml is empty")

    monkeypatch.setattr(doctor, "load_schema", explode)

    report = doctor.inspect()

    assert report["schema"] is None
    assert report["problems"] == ["schema unusable: fields.yaml is empty"]
    assert doctor.main([]) == 2


def test_a_problem_found_in_a_loadable_pack_exits_one(tmp_path, monkeypatch, capsys):
    bad = [load_bundle(_write_bundle(tmp_path, "novector", {"test_vectors": []}))]
    monkeypatch.setattr(doctor, "load_bundles", lambda *args, **kwargs: bad)

    assert doctor.main([]) == 1
    assert "PROBLEMS (" in capsys.readouterr().out


def test_healthy_pack_exits_zero_and_prints_the_pack(capsys):
    assert doctor.main([]) == 0

    out = capsys.readouterr().out
    assert "OK: no problems found" in out
    assert "guarantee-core" in out
    assert "GR-AMOUNT-POSITIVE" in out


def test_json_output_is_the_same_report(capsys):
    assert doctor.main(["--json"]) == 0

    assert json.loads(capsys.readouterr().out) == doctor.inspect()