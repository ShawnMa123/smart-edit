"""Tasks 13.1-13.6 — template units in the plan, the runner, the report baseline and the gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.audit.gate import evaluate_gate
from app.audit.planner import TEMPLATE_RESOLUTION_UNIT, build_plan
from app.audit.project import project_issue
from app.audit.resolve import AMBIGUOUS
from app.audit.runner import audit_state
from app.llm import resolve_llm
from app.rules.bundles import load_bundles
from app.rules.schema import load_schema
from app.rules.templates import load_template, load_templates, merge_schema
from app.runs import RunStore

PACK = load_template(Path("app/templates/adidas-guarantee.yaml"))

VALUES = {
    "guarantee_number": "BG-2026-00417",
    "guarantee_amount": "500000.00",
    "currency": "USD",
    "applicant_name": "Alpha Tech Pte Ltd",
    "beneficiary_name": "Adidas AG",
    "issue_date": "2026-03-12",
    "expiry_date": "2027-03-12",
    "governing_rules": "URDG 758",
}
DOCUMENT = "\n".join(
    [
        "DEMAND GUARANTEE",
        *(f"{key}: {value}" for key, value in VALUES.items()),
        "Payment shall be made in USD within 30 days of presentation.",
        "This guarantee is governed by the laws of England and Wales.",
        "We confirm the funds are from lawful sources.",
    ]
)


def _field(key: str, value: str, *, status: str = "extracted") -> dict:
    return {
        "key": key,
        "value": value,
        "status": status,
        "confirmed": False,
        "edited_by_user": False,
        "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": value, "form_label": None}
        if status == "extracted"
        else None,
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


def _state(*, extra: dict | None = None, business_type: str = "guarantee") -> dict:
    return {
        "business_type": business_type,
        "docs": [{"file_id": "F-1", "full_text": DOCUMENT}],
        "fields": {key: _field(key, value) for key, value in VALUES.items()},
        "extra_fields": {key: _field(key, value) for key, value in (extra or {}).items()},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "op": "read"}],
    }


def test_template_units_join_the_plan_and_the_total_is_conserved():
    """13.1 Six template units (3 fields + 2 clauses + 1 declaration) join the plan; counts still add up."""
    schema = merge_schema(load_schema(), [PACK])
    plan = build_plan(schema, load_bundles(), templates=[PACK])
    resolution_plan = build_plan(load_schema(), load_bundles(), resolution_reason="ambiguous_template")

    template_units = [unit for unit in plan if unit.family == "template"]
    assert len(template_units) == 6
    assert len({unit.check_id for unit in plan}) == len(plan)
    # 39 base schema units + `origin_country`'s type unit + 6 rules + 6 evidence + 6 template units
    assert len(plan) == 58
    assert [unit.check_id for unit in resolution_plan if unit.family == "template"] == [
        TEMPLATE_RESOLUTION_UNIT
    ]


def test_a_template_run_plans_and_assesses_its_units():
    """13.2 A templated audit runs the expectations through the engine and the clauses over the text."""
    result = audit_state(
        _state(extra={"origin_country": "VN"}), snapshot_digest="d-1", templates=[PACK]
    )
    report = result["report"]

    assert report["planned"] == 58
    by_id = {unit.check_id: unit for unit in result["units"]}
    statuses = {item.check_id: item.status for item in result["results"]}
    assert statuses["TEMPLATE:adidas-guarantee:field:currency"] == "pass"
    assert statuses["TEMPLATE:adidas-guarantee:field:origin_country"] == "pass"
    assert statuses["TEMPLATE:adidas-guarantee:clause:adidas-payment-clause"] == "pass"
    assert statuses["TEMPLATE:adidas-guarantee:declaration:lawful-source"] == "pass"
    assert by_id["TEMPLATE:adidas-guarantee:field:origin_country"].field_id == "origin_country"


def test_a_template_field_comes_from_extra_fields_and_respects_binding():
    """13.2 `origin_country` is not in fields.yaml: extra_fields is where it arrives."""
    wrong = audit_state(
        _state(extra={"origin_country": "CN"}), snapshot_digest="d-1", templates=[PACK]
    )
    unconfirmed = audit_state(
        _state(extra={}), snapshot_digest="d-1", templates=[PACK]
    )

    statuses = {item.check_id: item.status for item in wrong["results"]}
    assert statuses["TEMPLATE:adidas-guarantee:field:origin_country"] == "finding"

    guess = {
        item.check_id: item.status for item in unconfirmed["results"]
    }["TEMPLATE:adidas-guarantee:field:origin_country"]
    assert guess == "needs_input", "an absent template field is a gap, not a pass"


def test_the_report_carries_the_template_baseline():
    """13.3 `verification.audit.template` names the template, the packs and the resolution basis."""
    report = audit_state(_state(extra={"origin_country": "VN"}), snapshot_digest="d-1", templates=[PACK])[
        "report"
    ]
    baseline = report["template"]

    assert baseline["requested"] is True
    assert baseline["template_id"] == "adidas-guarantee"
    assert baseline["version"] == "1.0.0"
    assert baseline["content_sha256"] == PACK.content_sha256
    assert baseline["synthetic"] is True, "the demo pack must be labelled as such"
    assert baseline["counterparty"] == "Adidas AG"
    assert baseline["document_types"] == ["guarantee"]
    assert baseline["resolved_from"]["counterparty_value"] == "Adidas AG"
    assert baseline["policy_packs"] == [
        {
            "pack_id": "guarantee-core",
            "version": "1.0.0",
            "owner": None,
            "valid_from": None,
            "valid_to": None,
            "source": "guarantee.yaml",
        }
    ]
    assert baseline["conflicts"] == []
    assert baseline["reason"] is None


def test_an_unresolvable_template_records_its_reason_instead_of_units():
    """13.3 No matching template: one resolution unit, and the baseline says why."""
    state = _state(extra={"origin_country": "VN"})
    state["fields"]["beneficiary_name"] = _field("beneficiary_name", "Beta Construction Ltd")

    result = audit_state(state, snapshot_digest="d-1", templates=[PACK])
    baseline = result["report"]["template"]
    statuses = {item.check_id: (item.status, item.reason_code) for item in result["results"]}

    assert baseline["template_id"] is None
    assert baseline["reason"] == "no_applicable_template"
    assert result["report"]["planned"] == 52
    assert statuses[TEMPLATE_RESOLUTION_UNIT] == ("unable_to_assess", "no_applicable_template")


def test_two_matching_templates_are_ambiguous_not_chosen(tmp_path):
    """13.3 Ambiguity is reported with the candidates, never resolved by load order."""
    import yaml

    second = tmp_path / "adidas-second.yaml"
    second.write_text(
        yaml.safe_dump(
            {
                "template_id": "adidas-second",
                "version": "2.0.0",
                "published": True,
                "document_types": ["guarantee"],
                "counterparty": {"name": "Adidas AG"},
                "fields": [{"key": "currency", "allowed_values": ["USD"], "gate_type": "advisory"}],
            }
        ),
        encoding="utf-8",
    )
    packs = [PACK, load_template(second)]

    result = audit_state(_state(extra={"origin_country": "VN"}), snapshot_digest="d-1", templates=packs)
    baseline = result["report"]["template"]

    assert baseline["reason"] == AMBIGUOUS
    assert {candidate["template_id"] for candidate in baseline["candidate_templates"]} == {
        "adidas-guarantee",
        "adidas-second",
    }
    assert result["report"]["outcome"] == "unable_to_assess"


def test_a_template_finding_is_projected_with_its_gate_type_and_anchor():
    """13.4 The Issue/Finding rows carry the template's gate type, never severity's."""
    state = _state(extra={"origin_country": "CN"})
    result = audit_state(state, snapshot_digest="d-1", templates=[PACK])
    units = {unit.check_id: unit for unit in result["units"]}
    outcome = next(
        item for item in result["results"] if item.check_id == "TEMPLATE:adidas-guarantee:field:origin_country"
    )

    issue = project_issue(outcome, units[outcome.check_id])

    assert issue["gate_type"] == "hard_block"
    assert issue["location"] == "origin_country"
    assert issue["method"] == "deterministic"
    assert outcome.finding["target_operations"], "a hard block names the operations it blocks"
    assert any(
        finding["field_id"] == "origin_country" for finding in result["report"]["findings"]
    )


def _pack_from(tmp_path, payload: dict):
    """Write a pack and load it, so a test can shape one policy disagreement exactly."""
    import yaml

    path = tmp_path / f"{payload['template_id']}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return load_template(path)


def test_the_gate_blocks_on_a_policy_conflict_and_on_a_template_change(tmp_path):
    """13.5 Two new ways to be unsure, both of which must not answer `allowed`."""
    conflicting = _pack_from(
        tmp_path,
        {
            "template_id": "adidas-strict",
            "version": "1.0.0",
            "published": True,
            "document_types": ["guarantee"],
            "counterparty": {"name": "Adidas AG"},
            "policy_packs": ["missing-pack"],
            "fields": [{"key": "currency", "allowed_values": ["USD"], "gate_type": "advisory"}],
        },
    )
    state = _state(extra={"origin_country": "VN"})
    result = audit_state(state, snapshot_digest="d-1", templates=[conflicting])
    report = result["report"]

    conflict_decision = evaluate_gate(
        report,
        operation="start_approval",
        candidate_digest="d-1",
        findings=report["findings"],
    )
    changed_decision = evaluate_gate(
        report,
        operation="start_approval",
        candidate_digest="d-1",
        findings=report["findings"],
        template_digest="a-different-template-hash",
    )

    assert "policy_conflict" in report["reasons"] or "missing_policy_pack" in report["reasons"]
    assert conflict_decision["decision"] != "allowed"
    assert "rule_conflict" in conflict_decision["reason_codes"]
    assert changed_decision["decision"] == "indeterminate"
    assert "template_changed" in changed_decision["reason_codes"]


def test_the_gate_accepts_a_report_bound_to_the_current_template():
    """13.5 The same report is fine while the template digest matches."""
    state = _state(extra={"origin_country": "VN"})
    report = audit_state(state, snapshot_digest="d-1", templates=[PACK])["report"]

    decision = evaluate_gate(
        report,
        operation="start_approval",
        candidate_digest="d-1",
        findings=report["findings"],
        template_digest=PACK.content_sha256,
    )

    assert "template_changed" not in decision["reason_codes"]


def test_an_untemplated_audit_is_exactly_the_51_unit_baseline():
    """15.1 With no template requested (or none published) nothing about the audit changes."""
    plain = audit_state(_state(extra={"origin_country": "VN"}), snapshot_digest="d-1")
    unpublished = audit_state(
        _state(extra={"origin_country": "VN"}),
        snapshot_digest="d-1",
        templates=[],  # an empty pool: the caller asked, but no pack is available
    )

    assert plain["report"]["planned"] == 51
    assert plain["report"]["coverage"] == {
        "assessed": 33,
        "not_applicable": 18,
        "unsettled": 0,
        "ratio": 0.647,
    }
    assert plain["report"]["outcome"] == "no_findings"
    assert plain["report"]["template"]["requested"] is False
    assert plain["report"]["template"]["reason"] == "template_not_requested"

    # An explicit request with nothing to resolve is loud, not silently ignored.
    assert unpublished["report"]["template"]["reason"] == "no_applicable_template"
    assert unpublished["report"]["planned"] == 52
    assert unpublished["report"]["outcome"] == "unable_to_assess"


def test_the_envelope_carries_the_template_baseline(tmp_path):
    """13.6 `verification.audit.template` after an audit, `null` before it."""
    store = RunStore(runs_dir=tmp_path / "runs")
    client = TestClient(
        create_app(store=store, llm=resolve_llm("fixture:fixtures/llm/extract_sample.json"))
    )
    text = Path("fixtures/llm/sample_document.txt").read_text(encoding="utf-8")
    thread_id = client.post("/runs", json={"text": text}).json()["thread_id"]

    before = client.get(f"/runs/{thread_id}").json()
    plain = client.post(f"/runs/{thread_id}/stages/audit").json()

    assert before["verification"] is None
    assert plain["verification"]["audit"]["template"]["requested"] is False
    assert plain["verification"]["audit"]["template"]["reason"] == "template_not_requested"
    assert plain["verification"]["audit"]["planned"] == 51