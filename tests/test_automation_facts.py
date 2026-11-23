"""Deterministic protected-fact checks."""

from __future__ import annotations

from app.automation.facts import assess_facts, extract_facts


def _values(text: str) -> set[tuple[str, str]]:
    return {(token.kind, token.value) for token in extract_facts(text)}


def test_extracts_amount_currency_date_percentage_and_legal_reference():
    values = _values("USD 500,000.00 due 2027-03-31, 5% under URDG 758")
    assert ("amount", "500000.00") in values
    assert ("currency", "USD") in values
    assert ("date", "2027-03-31") in values
    assert ("percentage", "5%") in values
    assert ("legal_reference", "URDG758") in values


def test_same_facts_are_not_risky():
    assessment = assess_facts(
        "Amount: USD 500,000.00, expires 2027-03-31.",
        "Amount: USD 500,000.00, expires 2027-03-31.",
    )
    assert not assessment.changed
    assert assessment.risk_flags == ()


def test_changed_amount_and_date_are_flagged():
    assessment = assess_facts(
        "Amount: USD 500,000.00, expires 2027-03-31.",
        "Amount: USD 600,000.00, expires 2028-03-31.",
        intent="replace_text",
    )
    assert assessment.changed
    assert "substantive_change" in assessment.risk_flags
    assert "changed_amount" in assessment.risk_flags
    assert "changed_date" in assessment.risk_flags


def test_polish_cannot_silently_change_a_fact():
    assessment = assess_facts(
        "Amount: USD 500,000.00.",
        "Amount: USD 600,000.00.",
        intent="polish",
    )
    assert assessment.requires_clarification
    assert assessment.risk_flags


def test_party_and_negation_are_detected():
    values = _values("Alpha Tech Pte Ltd shall not assign.")
    assert any(kind == "party" and "Alpha Tech" in value for kind, value in values)
    assert any(kind == "negation" for kind, _ in values)
    assert any(kind == "obligation" for kind, _ in values)