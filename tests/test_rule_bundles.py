"""Tasks 2.4-2.6 — bundle loading, integrity and executable rule vectors."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.audit.bind import ABSENT, CONFIRMED, UNCONFIRMED, AuditValue
from app.rules.bundles import (
    BundleError,
    bundle_versions,
    find_conflicts,
    load_bundle,
    load_bundles,
    validate_against_schema,
)
from app.rules.engine import evaluate_rule
from app.rules.schema import load_schema

CTX = {"schema": load_schema()}
BUNDLE_PATH = Path("app/rules/bundles/guarantee.yaml")


def _bundle():
    return load_bundle(BUNDLE_PATH)


def _values(fields: dict) -> dict[str, AuditValue]:
    states = {"absent": ABSENT, "confirmed": CONFIRMED, "unconfirmed": UNCONFIRMED}
    return {
        field_id: AuditValue(field_id, states[spec["state"]], spec.get("value"))
        for field_id, spec in fields.items()
    }


def test_bundle_metadata_and_hash():
    bundle = _bundle()

    assert bundle.bundle_id == "guarantee-core"
    assert bundle.version == "1.0.0"
    assert bundle.published is True
    assert len(bundle.content_sha256) == 12
    assert {rule["rule_id"] for rule in bundle.rules} >= {
        "GR-AMOUNT-POSITIVE",
        "GR-EXPIRY-AFTER-ISSUE",
        "GR-AMOUNT-REQUIRES-CURRENCY",
    }


def test_every_rule_declares_governance_fields():
    for rule in _bundle().rules:
        assert rule["severity"] in ("critical", "warn", "info")
        assert rule["gate_type"] in ("advisory", "human_review", "hard_block")
        assert isinstance(rule.get("target_operations"), list)

    positive = next(rule for rule in _bundle().rules if rule["rule_id"] == "GR-AMOUNT-POSITIVE")
    assert positive["severity"] == "critical"
    assert positive["gate_type"] == "hard_block"
    assert "start_approval" in positive["target_operations"]


def test_every_rule_has_executable_vectors():
    """Task 2.6 / O4 — a rule must demonstrate pass, finding **and** needs_input."""
    required = {"pass", "finding", "needs_input"}
    for rule in _bundle().rules:
        vectors = rule.get("test_vectors") or []
        assert vectors, f"{rule['rule_id']} has no test vectors"
        statuses = set()
        for vector in vectors:
            result = evaluate_rule(rule, _values(vector["fields"]), CTX)
            assert result.status == vector["expect"], (
                f"{rule['rule_id']} / {vector['name']}: expected {vector['expect']}, got {result.status}"
            )
            statuses.add(result.status)
        missing = required - statuses
        assert not missing, f"{rule['rule_id']} has no vector producing {sorted(missing)}"


def test_unpublished_bundles_are_ignored(tmp_path):
    draft = tmp_path / "draft.yaml"
    draft.write_text(
        yaml.safe_dump(
            {
                "bundle_id": "draft",
                "version": "0.1.0",
                "published": False,
                "rules": [
                    {
                        "rule_id": "DRAFT-1",
                        "version": 1,
                        "title": "draft",
                        "severity": "warn",
                        "gate_type": "advisory",
                        "expression": {"op": "exists", "field_id": "currency"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_bundles(tmp_path) == []
    assert len(load_bundles(tmp_path, include_unpublished=True)) == 1


def test_malformed_bundle_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump({"bundle_id": "bad", "version": "1", "published": True, "rules": [{"rule_id": "X"}]}),
        encoding="utf-8",
    )
    with pytest.raises(BundleError, match="missing"):
        load_bundle(bad)


def test_semantic_rule_cannot_be_hard_block(tmp_path):
    bad = tmp_path / "semantic.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "bundle_id": "semantic",
                "version": "1",
                "published": True,
                "rules": [
                    {
                        "rule_id": "SEM-1",
                        "version": 1,
                        "title": "model opinion",
                        "severity": "critical",
                        "gate_type": "hard_block",
                        "method": "semantic",
                        "expression": {"op": "exists", "field_id": "currency"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BundleError, match="never be hard_block"):
        load_bundle(bad)


def test_conflicting_rule_versions_are_reported(tmp_path):
    def write(name: str, version: str, rule_version: int) -> None:
        (tmp_path / name).write_text(
            yaml.safe_dump(
                {
                    "bundle_id": name,
                    "version": version,
                    "published": True,
                    "rules": [
                        {
                            "rule_id": "GR-AMOUNT-POSITIVE",
                            "version": rule_version,
                            "title": "dup",
                            "severity": "critical",
                            "gate_type": "hard_block",
                            "expression": {"op": "exists", "field_id": "guarantee_amount"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    write("bank.yaml", "1.0.0", 1)
    write("client.yaml", "1.0.0", 2)

    conflicts = find_conflicts(load_bundles(tmp_path))

    assert conflicts and "GR-AMOUNT-POSITIVE" in conflicts[0]


def test_bundle_versions_map_is_reported():
    versions = bundle_versions(load_bundles())

    assert versions == {"guarantee-core": "1.0.0"}


def _write_bundle(tmp_path, name: str, rule: dict) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "bundle_id": name,
                "version": "1.0.0",
                "published": True,
                "rules": [
                    {
                        "rule_id": rule.pop("rule_id", "T-1"),
                        "version": 1,
                        "title": "t",
                        "severity": "warn",
                        "gate_type": "advisory",
                        **rule,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_published_bundle_is_valid_against_the_schema():
    validate_against_schema(_bundle(), load_schema())  # no raise


def test_rule_referencing_an_unknown_field_is_rejected(tmp_path):
    """A typo in a rule id must not silently become 'not applicable' on every document."""
    path = _write_bundle(
        tmp_path, "typo", {"expression": {"op": "exists", "field_id": "guarantee_ammount"}}
    )

    with pytest.raises(BundleError, match="unknown field"):
        validate_against_schema(load_bundle(path), load_schema())


def test_rule_comparing_incompatible_types_is_rejected_at_load_time(tmp_path):
    path = _write_bundle(
        tmp_path,
        "badcompare",
        {
            "expression": {
                "op": "compare",
                "left": {"kind": "field", "field_id": "currency"},
                "comparator": "eq",
                "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
            }
        },
    )

    with pytest.raises(BundleError, match="cannot be compared"):
        validate_against_schema(load_bundle(path), load_schema())


def test_runner_refuses_a_bundle_that_does_not_match_the_schema(tmp_path):
    from app.audit.runner import audit_state

    path = _write_bundle(
        tmp_path, "typo2", {"expression": {"op": "exists", "field_id": "no_such_field"}}
    )

    with pytest.raises(BundleError, match="unknown field"):
        audit_state(
            {"fields": {}, "extra_fields": {}, "findings": [], "trail": [], "docs": []},
            bundles=[load_bundle(path)],
            snapshot_digest="digest-1",
        )


def test_runner_requires_a_snapshot_digest():
    """A report that cannot name its snapshot can never go stale — so the digest is required."""
    from app.audit.runner import AuditRunError, audit_state

    with pytest.raises(AuditRunError, match="snapshot_digest is required"):
        audit_state({"fields": {}}, snapshot_digest="")


def test_two_sources_disagreeing_about_a_gate_type_is_a_conflict(tmp_path):
    """One source says hard-block, another says advisory for the same field: the gate cannot honour both."""
    def publish(name: str, gate_type: str):
        path = tmp_path / f"{name}.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "bundle_id": name,
                    "version": "1.0.0",
                    "published": True,
                    "rules": [
                        {
                            "rule_id": f"{name.upper()}-AMOUNT",
                            "version": 1,
                            "title": "amount",
                            "severity": "warn",
                            "gate_type": gate_type,
                            "category": "field",
                            "field_id": "guarantee_amount",
                            "expression": {"op": "exists", "field_id": "guarantee_amount"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return load_bundle(path)

    conflicts = find_conflicts([publish("bank", "hard_block"), publish("client", "advisory")])

    assert len(conflicts) == 1
    assert "gated inconsistently" in conflicts[0]
    assert "hard_block in bank" in conflicts[0]
    assert "advisory in client" in conflicts[0]


def test_one_bundle_may_carry_both_gate_types_for_a_field():
    """Our own pack has a hard-block and an advisory rule for `guarantee_amount`; that is not a conflict."""
    assert find_conflicts(load_bundles()) == []