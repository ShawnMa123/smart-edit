"""Tasks 8.1-8.3 — the evidence family."""

from __future__ import annotations

import pytest

from app.audit import evidence
from app.audit.evidence import NOT_RUN_REASON, evaluate_all, evaluate_evidence_unit
from app.audit.planner import evidence_units
from app.rules.types import FAILED, FINDING, NOT_APPLICABLE, PASS, Unit

UNITS = {unit.check_id: unit for unit in evidence_units()}


def _source(span: str = "USD 500,000.00") -> dict:
    return {"file_id": "F-1", "page": 1, "bbox": None, "span": span, "form_label": None}


def _state(**over) -> dict:
    base = {
        "docs": [{"file_id": "F-1", "full_text": "Amount: USD 500,000.00"}],
        "fields": {
            "guarantee_amount": {
                "key": "guarantee_amount",
                "value": "500000.00",
                "status": "extracted",
                "source": _source(),
                "notes": [],
            }
        },
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "op": "read"}],
    }
    base.update(over)
    return base


def _run(name: str, state: dict):
    return evaluate_evidence_unit(UNITS[f"EVIDENCE:{name}"], state)


def test_clean_inputs_pass():
    assert _run("trail_overreach", _state()).status == PASS
    assert _run("provenance", _state()).status == PASS


def test_overreach_is_reported_with_the_entry_id():
    state = _state(trail=[{"id": "agent1.normalize#009", "op": "drop"}])
    result = _run("trail_overreach", state)

    assert result.status == FINDING
    assert result.finding["detail"]["entry_ids"] == ["agent1.normalize#009"]
    assert result.finding["gate_type"] == "hard_block"
    assert "start_approval" in result.finding["target_operations"]


def test_untraceable_extracted_value_is_reported():
    no_source = _state(
        fields={
            "guarantee_amount": {
                "key": "guarantee_amount",
                "value": "500000.00",
                "status": "extracted",
                "source": None,
                "notes": [],
            }
        }
    )
    wrong_span = _state(
        fields={
            "guarantee_amount": {
                "key": "guarantee_amount",
                "value": "500000.00",
                "status": "extracted",
                "source": _source("an amount that is not in the text"),
                "notes": [],
            }
        }
    )

    assert _run("provenance", no_source).status == FINDING
    assert _run("provenance", wrong_span).status == FINDING
    assert _run("provenance", no_source).finding["detail"]["field_ids"] == ["guarantee_amount"]


def test_provenance_is_not_applicable_without_extracted_values():
    state = _state(fields={"guarantee_amount": {"key": "guarantee_amount", "value": None, "status": "missing"}})
    result = _run("provenance", state)

    assert result.status == NOT_APPLICABLE
    assert result.reason_code == "no_extracted_values"


def test_dangling_anchor_is_reported():
    dangling = _state(findings=[{"id": "N-001", "severity": "warn", "field_keys": ["ghost_field"]}])
    resolvable = _state(findings=[{"id": "N-001", "severity": "warn", "field_keys": ["guarantee_amount"]}])

    assert _run("finding_anchor", dangling).status == FINDING
    assert _run("finding_anchor", dangling).finding["detail"]["finding_ids"] == ["N-001"]
    assert _run("finding_anchor", resolvable).status == PASS


def test_the_conflict_check_says_which_upstream_output_it_needs():
    result = _run("conclusion_conflict", _state())

    assert result.status == NOT_APPLICABLE
    assert result.reason_code == "requires_agent_verify_output"


def _review_state(**over) -> dict:
    state = _state(
        legal={
            "input_mode": "enriched",
            "applicable_rules": [],
            "claims": [
                {
                    "text": "URDG 758 governs this guarantee for USD 500,000.00 issued in Singapore",
                    "chunk_id": "chunk-1",
                    "kind": "applicable_rule",
                    "support": "supported",
                }
            ],
            "coverage": {"unavailable": False, "business_type_uncertain": False, "notes": []},
            "escalate_to_human": False,
            "summary": "The guarantee is governed by URDG 758.",
        },
        retrieved=[
            {
                "chunk_id": "chunk-1",
                "doc_id": "kb-1",
                "title": "URDG 758",
                "text": "URDG 758 applies to guarantees issued in Singapore; the amount is USD 500,000.00.",
                "score": 0.9,
                "source_type": "kb",
            }
        ],
    )
    state.update(over)
    return state


def test_citation_support_is_not_applicable_without_regulatory_output():
    result = _run("citation_support", _state())

    assert result.status == NOT_APPLICABLE
    assert result.reason_code == "no_regulatory_claims"


def test_fabricated_chunk_id_is_a_hard_block():
    state = _review_state(
        legal={
            **_review_state()["legal"],
            "claims": [
                {
                    "text": "URDG 758 governs this guarantee",
                    "chunk_id": "chunk-missing",
                    "kind": "applicable_rule",
                    "support": "supported",
                }
            ],
        }
    )

    result = _run("citation_support", state)

    assert result.status == FINDING
    assert result.finding["severity"] == "critical"
    assert result.finding["gate_type"] == "hard_block"
    assert result.finding["detail"]["chunk_ids"] == ["chunk-missing"]
    assert "start_approval" in result.finding["target_operations"]


def test_entity_missing_from_cited_chunk_is_a_hard_block():
    state = _review_state(
        legal={
            **_review_state()["legal"],
            "claims": [
                {
                    "text": "The guarantee is USD 750,000.00",
                    "chunk_id": "chunk-1",
                    "kind": "risk",
                    "support": "supported",
                }
            ],
        }
    )

    result = _run("citation_support", state)

    assert result.status == FINDING
    assert result.finding["gate_type"] == "hard_block"
    assert result.finding["detail"]["entity_gaps"][0]["missing_entities"] == ["amount:USD750000.00"]


def test_insufficient_claim_with_chunk_is_a_warning():
    state = _review_state(
        legal={
            **_review_state()["legal"],
            "claims": [
                {
                    "text": "URDG 758 governs this guarantee",
                    "chunk_id": "chunk-1",
                    "kind": "applicable_rule",
                    "support": "insufficient",
                }
            ],
        }
    )

    result = _run("citation_support", state)

    assert result.status == FINDING
    assert result.finding["severity"] == "warn"
    assert result.finding["gate_type"] == "advisory"


def test_citation_support_passes_when_claims_are_supported():
    assert _run("citation_support", _review_state()).status == PASS


def test_coverage_is_not_applicable_without_legal():
    result = _run("coverage_declaration", _state())

    assert result.status == NOT_APPLICABLE
    assert result.reason_code == "no_regulatory_output"


def test_unavailable_without_declaration_is_a_hard_block():
    state = _review_state(
        legal={
            **_review_state()["legal"],
            "coverage": {"unavailable": True, "business_type_uncertain": False, "notes": []},
            "summary": "Everything looks fine.",
        }
    )

    result = _run("coverage_declaration", state)

    assert result.status == FINDING
    assert result.finding["severity"] == "critical"
    assert result.finding["gate_type"] == "hard_block"


def test_claimed_coverage_without_retrieval_is_a_hard_block():
    state = _review_state(retrieved=[])

    result = _run("coverage_declaration", state)

    assert result.status == FINDING
    assert result.finding["detail"]["retrieved"] == 0
    assert result.finding["gate_type"] == "hard_block"


def test_uncertain_business_type_without_note_is_a_warning():
    state = _review_state(
        legal={
            **_review_state()["legal"],
            "coverage": {"unavailable": False, "business_type_uncertain": True, "notes": []},
            "summary": "The guarantee is governed by URDG 758.",
        }
    )

    result = _run("coverage_declaration", state)

    assert result.status == FINDING
    assert result.finding["severity"] == "warn"
    assert result.finding["gate_type"] == "advisory"


def test_coverage_declaration_passes_when_gaps_are_declared():
    state = _review_state(
        legal={
            **_review_state()["legal"],
            "coverage": {
                "unavailable": True,
                "business_type_uncertain": True,
                "notes": ["business type uncertain; coverage unavailable"],
            },
            "summary": "法规建议未覆盖；业务类型不确定。",
        }
    )

    assert _run("coverage_declaration", state).status == PASS


def test_a_crashing_check_does_not_take_the_audit_down(monkeypatch):
    def boom(unit, state):
        raise RuntimeError("checker exploded")

    monkeypatch.setitem(evidence._CHECKS, "provenance", boom)
    units = list(UNITS.values())

    results = evaluate_all(units, _state())

    statuses = {result.check_id: result.status for result in results}
    assert statuses["EVIDENCE:provenance"] == FAILED
    assert statuses["EVIDENCE:trail_overreach"] == PASS, "the other checks still ran"
    assert statuses["EVIDENCE:citation_support"] == NOT_APPLICABLE
    crash = next(result for result in results if result.check_id == "EVIDENCE:provenance")
    assert "checker_crashed" in (crash.reason_code or "")


def test_unknown_evidence_unit_is_not_applicable():
    result = evaluate_evidence_unit(Unit(check_id="EVIDENCE:mystery", family="evidence"), _state())

    assert result.status == NOT_APPLICABLE
    assert result.reason_code == NOT_RUN_REASON