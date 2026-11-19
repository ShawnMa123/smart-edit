"""L1 legal review slice: the deterministic core (spec LT-01~04, rule part).

Hard invariant under test: a missing field is a finding or needs_input, NEVER a pass;
an empty facts payload must not produce "no_findings".
"""

from __future__ import annotations

from decimal import Decimal

from app.legal_review.rules import evaluate
from app.legal_review.service import create_review, run_deterministic
from app.legal_review.contracts import ReviewCreate


def _submit(facts: dict):
    request = ReviewCreate(
        workspace_id="ws_demo",
        document_id="doc_demo",
        snapshot_id="snap_01",
        facts_version_id="facts_01",
        modes=["deterministic"],
    )
    return create_review(request, facts)


def test_amount_missing_is_a_finding_not_a_pass():
    run, report = _submit({})
    assert run.status == "succeeded"
    assert report.outcome == "findings_present"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.severity == "Critical"
    assert finding.gate_type == "hard_block"
    assert finding.rule_refs[0].rule_id == "DEMO-AMOUNT-REQUIRED"


def test_amount_confirmed_passes():
    run, report = _submit({"amount": {"state": "confirmed", "value": "500000.00"}})
    assert report.outcome == "no_findings"
    assert report.findings == []
    assert report.coverage[0].status == "pass"


def test_amount_unconfirmed_is_unable_to_assess():
    run, report = _submit({"amount": {"state": "unconfirmed"}})
    assert report.coverage[0].status == "unable_to_assess"
    assert report.findings == []


def test_rule_expression_three_valued_logic():
    # exists: missing -> False, unconfirmed -> None, confirmed+value -> True
    assert evaluate({"op": "exists", "field_id": "amount"}, {}) is False
    assert evaluate({"op": "exists", "field_id": "amount"}, {"amount": {"state": "unconfirmed"}}) is None
    assert evaluate({"op": "exists", "field_id": "amount"}, {"amount": {"state": "confirmed", "value": "1"}}) is True


def test_compare_operators():
    facts = {"amount": {"state": "confirmed", "value": Decimal("100")}}
    assert evaluate({"op": "compare", "left": {"kind": "field", "field_id": "amount"}, "comparator": "gt", "right": {"kind": "literal", "value_type": "decimal", "value": "50"}}, facts) is True
    assert evaluate({"op": "compare", "left": {"kind": "field", "field_id": "amount"}, "comparator": "lt", "right": {"kind": "literal", "value_type": "decimal", "value": "50"}}, facts) is False
    # missing field is unknown, not a mismatch
    assert evaluate({"op": "compare", "left": {"kind": "field", "field_id": "nope"}, "comparator": "eq", "right": {"kind": "literal", "value": "x"}}, facts) is None


def test_compare_incompatible_types_are_unknown_not_mismatch():
    # string field vs decimal literal: no implicit conversion (spec §4.2)
    facts = {"amount": {"state": "confirmed", "value": "100"}}
    assert evaluate({"op": "compare", "left": {"kind": "field", "field_id": "amount"}, "comparator": "gt", "right": {"kind": "literal", "value_type": "decimal", "value": "50"}}, facts) is None
