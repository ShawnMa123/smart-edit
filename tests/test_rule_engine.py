"""Tasks 2.2 / 2.3 — three-valued evaluation and the purity guard."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.audit.bind import ABSENT, CONFIRMED, UNCONFIRMED, VIOLATION, AuditValue
from app.rules import engine
from app.rules.dsl import validate
from app.rules.engine import evaluate_expression, evaluate_rule, evaluate_schema_check
from app.rules.schema import load_schema
from app.rules.types import (
    FAILED,
    FINDING,
    NEEDS_INPUT,
    NOT_APPLICABLE,
    PASS,
    RuleEvaluationError,
    Tri,
    Unit,
)

AMOUNT = AuditValue("guarantee_amount", CONFIRMED, "500000.00")
ZERO = AuditValue("guarantee_amount", CONFIRMED, "0.00")
MISSING = AuditValue("guarantee_amount", ABSENT)
GUESS = AuditValue("guarantee_amount", UNCONFIRMED, "500000.00")
BROKEN = AuditValue("guarantee_amount", VIOLATION, "500000.00")
CURRENCY = AuditValue("currency", CONFIRMED, "USD")
OTHER_MISSING = AuditValue("applicant_name", ABSENT)
VALUES = {"guarantee_amount": AMOUNT, "currency": CURRENCY}
# Comparison needs the declared field types: a normalized string is never compared as a decimal.
CTX = {"schema": load_schema()}


def _exists(field_id: str) -> dict:
    return {"op": "exists", "field_id": field_id}


def test_exists_separates_absent_from_unconfirmed():
    assert evaluate_expression(_exists("guarantee_amount"), VALUES) == (Tri.TRUE, None)
    assert evaluate_expression(_exists("guarantee_amount"), {"guarantee_amount": MISSING}) == (Tri.FALSE, None)
    assert evaluate_expression(_exists("guarantee_amount"), {"guarantee_amount": GUESS})[0] is Tri.UNKNOWN
    assert evaluate_expression(_exists("guarantee_amount"), {"guarantee_amount": BROKEN})[0] is Tri.UNKNOWN


def test_all_and_any_keep_unknown_but_let_a_verdict_win():
    unknown = _exists("guarantee_amount")  # unconfirmed ⇒ unknown
    absent_other = _exists("applicant_name")  # absent ⇒ false
    present = _exists("currency")  # confirmed ⇒ true
    values = {"guarantee_amount": GUESS, "applicant_name": OTHER_MISSING, "currency": CURRENCY}

    assert evaluate_expression({"op": "all", "args": [unknown, absent_other]}, values)[0] is Tri.FALSE
    assert evaluate_expression({"op": "any", "args": [unknown, present]}, values)[0] is Tri.TRUE
    assert evaluate_expression({"op": "all", "args": [unknown]}, values)[0] is Tri.UNKNOWN
    assert evaluate_expression({"op": "any", "args": [unknown]}, values)[0] is Tri.UNKNOWN


def test_not_keeps_unknown():
    tri, _ = evaluate_expression({"op": "not", "arg": _exists("guarantee_amount")}, {"guarantee_amount": GUESS})
    assert tri is Tri.UNKNOWN


def test_compare_is_typed_and_never_converts():
    positive = {
        "op": "compare",
        "left": {"kind": "field", "field_id": "guarantee_amount"},
        "comparator": "gt",
        "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
    }
    assert evaluate_expression(positive, VALUES, CTX) == (Tri.TRUE, None)
    assert evaluate_expression(positive, {"guarantee_amount": ZERO}, CTX) == (Tri.FALSE, None)
    assert evaluate_expression(positive, {"guarantee_amount": GUESS}, CTX) == (Tri.UNKNOWN, "unconfirmed")

    mismatched = {**positive, "left": {"kind": "field", "field_id": "currency"}}
    assert evaluate_expression(mismatched, VALUES, CTX) == (Tri.UNKNOWN, "rule_type_mismatch")


def test_unparsable_document_value_is_a_document_problem():
    """A value that does not parse is a document defect (the schema check reports it), not a rule defect."""
    positive = {
        "op": "compare",
        "left": {"kind": "field", "field_id": "guarantee_amount"},
        "comparator": "gt",
        "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
    }
    values = {"guarantee_amount": AuditValue("guarantee_amount", CONFIRMED, "not-a-number")}

    assert evaluate_expression(positive, values, CTX) == (Tri.UNKNOWN, "value_unparsable")


def test_incomparable_rule_fails_loudly_instead_of_degrading():
    """A rule bug must surface as `failed`, not as 'unable to assess' on every document."""
    rule = {
        "rule_id": "BAD-TYPES",
        "version": 1,
        "field_id": "currency",
        "expression": {
            "op": "compare",
            "left": {"kind": "field", "field_id": "currency"},
            "comparator": "eq",
            "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
        },
    }

    result = evaluate_rule(rule, VALUES, CTX)

    assert result.status == FAILED
    assert result.reason_code == "rule_type_mismatch"


def test_integer_field_compares_against_a_decimal_literal():
    """`LITERAL_COMPATIBILITY` allows integer→decimal, so the engine must honour it (regression)."""
    expression = {
        "op": "compare",
        "left": {"kind": "field", "field_id": "tenor_days"},
        "comparator": "gt",
        "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
    }
    values = {"tenor_days": AuditValue("tenor_days", CONFIRMED, "720")}

    assert evaluate_expression(expression, values, CTX) == (Tri.TRUE, None)

    rule = {"rule_id": "GR-TENOR", "version": 1, "field_id": "tenor_days", "expression": expression}
    assert evaluate_rule(rule, values, CTX).status == PASS


def test_datetime_literal_cannot_be_compared_with_a_date_field():
    """`datetime` subclasses `date`; exact-type comparison keeps that a rule error."""
    expression = {
        "op": "compare",
        "left": {"kind": "field", "field_id": "issue_date"},
        "comparator": "gt",
        "right": {"kind": "literal", "value_type": "datetime", "value": "2026-01-01T00:00:00"},
    }
    values = {"issue_date": AuditValue("issue_date", CONFIRMED, "2026-03-12")}

    assert evaluate_expression(expression, values, CTX) == (Tri.UNKNOWN, "rule_type_mismatch")


def test_an_impossible_date_is_reported_as_an_invalid_value():
    """Spec 'Date rules use business dates and real calendars' — a real calendar, not a format check.

    `2026-02-30` matches `YYYY-MM-DD` but does not exist, so the schema unit must produce a finding
    (the value is invalid) instead of quietly passing or becoming 'unable to assess'.
    """
    schema = CTX["schema"]
    unit = Unit(check_id="SCHEMA:issue_date:type", family="schema")

    result = evaluate_schema_check(
        unit,
        schema.fields["issue_date"],
        AuditValue("issue_date", CONFIRMED, "2026-02-30"),
        schema.version,
    )

    assert result.status == FINDING
    assert result.detail == {"reason": "invalid_value"}
    assert result.finding["field_id"] == "issue_date"
    assert result.finding["rule_ref"]["rule_id"] == "SCHEMA:issue_date:type"


def test_a_working_day_calendar_rule_is_refused_instead_of_guessed():
    """Spec: a calendar this build has no versioned source for must never be guessed.

    The POC has no working-day/holiday calendar, so the closed op set makes such a rule unauthorable:
    it is refused at load time rather than answered with a made-up business day.
    """
    with pytest.raises(RuleEvaluationError, match="unknown op"):
        validate({"op": "business_day", "field_id": "issue_date"})


def test_length_units_and_encoding_failure():
    code_points = {"op": "length", "field_id": "guarantee_amount", "unit": "code_point", "max": 3}
    assert evaluate_expression(code_points, VALUES) == (Tri.FALSE, None)

    bytes_ok = {"op": "length", "field_id": "currency", "unit": "byte", "encoding": "ascii", "max": 3}
    assert evaluate_expression(bytes_ok, VALUES) == (Tri.TRUE, None)

    unencodable = {"op": "length", "field_id": "applicant_name", "unit": "byte", "encoding": "ascii"}
    with pytest.raises(engine.RuleEvaluationError, match="encoding_failed"):
        evaluate_expression(unencodable, {"applicant_name": AuditValue("applicant_name", CONFIRMED, "阿尔法")})

    graphemes = {"op": "length", "field_id": "currency", "unit": "grapheme", "max": 3}
    with pytest.raises(engine.RuleEvaluationError, match="unsupported_unit"):
        evaluate_expression(graphemes, VALUES)


def test_charset_uses_the_catalogue():
    upper = {"op": "charset", "field_id": "currency", "charset_id": "upper_alpha"}
    assert evaluate_expression(upper, VALUES) == (Tri.TRUE, None)
    assert evaluate_expression(upper, {"currency": AuditValue("currency", CONFIRMED, "usd")}) == (Tri.FALSE, None)


def test_contains_clause_uses_the_shared_normalisation():
    clause = {
        "op": "contains_clause",
        "field_id": "governing_rules",
        "match_kind": "exact_text",
        "value": "URDG 758",
    }
    values = {"governing_rules": AuditValue("governing_rules", CONFIRMED, "适用 URDG　７５８")}
    assert evaluate_expression(clause, values) == (Tri.TRUE, None)


def test_a_missing_checked_field_is_never_pre_swallowed():
    """Design D5: applicability must not consume the field the rule is about."""
    rule = {
        "rule_id": "GR-AMOUNT-POSITIVE",
        "version": 1,
        "title": "amount positive",
        "severity": "critical",
        "gate_type": "hard_block",
        "target_operations": ["start_approval"],
        "field_id": "guarantee_amount",
        "applicability": _exists("currency"),
        "expression": _exists("guarantee_amount"),
    }

    result = evaluate_rule(rule, {"guarantee_amount": MISSING, "currency": CURRENCY})

    assert result.status == FINDING
    assert result.finding["rule_ref"] == {"rule_id": "GR-AMOUNT-POSITIVE", "version": 1}


def test_rule_outcomes():
    rule = {
        "rule_id": "GR-AMOUNT-POSITIVE",
        "version": 1,
        "field_id": "guarantee_amount",
        "expression": {
            "op": "compare",
            "left": {"kind": "field", "field_id": "guarantee_amount"},
            "comparator": "gt",
            "right": {"kind": "literal", "value_type": "decimal", "value": "0"},
        },
    }

    assert evaluate_rule(rule, VALUES, CTX).status == PASS
    assert evaluate_rule(rule, {"guarantee_amount": ZERO}, CTX).status == FINDING
    assert evaluate_rule(rule, {"guarantee_amount": GUESS}, CTX).status == NEEDS_INPUT

    # Applicability on a *different* field that is absent ⇒ the rule genuinely does not apply.
    # (The trap §5.1 warns about is using the checked field itself there — covered separately.)
    assert (
        evaluate_rule(
            {**rule, "applicability": _exists("currency")},
            {"currency": AuditValue("currency", ABSENT)},
            CTX,
        ).status
        == NOT_APPLICABLE
    )
    # Applicability on an *unconfirmed* field ⇒ unknown ⇒ needs_input, never not_applicable.
    assert (
        evaluate_rule(
            {**rule, "applicability": _exists("currency")},
            {"currency": AuditValue("currency", UNCONFIRMED, "USD")},
            CTX,
        ).status
        == NEEDS_INPUT
    )

    unsupported = {
        **rule,
        "expression": {"op": "length", "field_id": "guarantee_amount", "unit": "grapheme", "max": 3},
    }
    assert evaluate_rule(unsupported, VALUES, CTX).status == FAILED


def test_not_applicable_when_applicability_is_false():
    rule = {
        "rule_id": "GR-ONLY-FOR-GUARANTEE",
        "version": 1,
        "applicability": _exists("nope"),
        "expression": _exists("guarantee_amount"),
    }

    assert evaluate_rule(rule, VALUES).status == NOT_APPLICABLE


def test_engine_is_pure():
    """Task 2.3: no model, no HTTP, no filesystem writes in the deterministic kernel."""
    forbidden = ("app.llm", "app.api", "requests", "httpx", "urllib", "socket")
    root = Path(engine.__file__).parent

    for module in ("engine.py", "dsl.py", "types.py", "schema.py"):
        source = (root / module).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{module} references {token}"

    assert not hasattr(engine, "resolve_llm")
    assert "write_text" not in inspect.getsource(engine)