"""Task 2.1 — the closed rule DSL rejects everything outside its vocabulary."""

from __future__ import annotations

import pytest

from app.rules.dsl import validate
from app.rules.types import RuleEvaluationError

FIELD = {"kind": "field", "field_id": "guarantee_amount"}
LITERAL = {"kind": "literal", "value_type": "decimal", "value": "0"}


def test_accepts_every_documented_op():
    for expression in [
        {"op": "exists", "field_id": "guarantee_amount"},
        {"op": "all", "args": [{"op": "exists", "field_id": "a"}]},
        {"op": "any", "args": [{"op": "exists", "field_id": "a"}, {"op": "exists", "field_id": "b"}]},
        {"op": "not", "arg": {"op": "exists", "field_id": "a"}},
        {"op": "compare", "left": FIELD, "comparator": "gt", "right": LITERAL},
        {"op": "length", "field_id": "a", "unit": "code_point", "max": 10},
        {"op": "length", "field_id": "a", "unit": "byte", "encoding": "utf-8", "max": 10},
        {"op": "charset", "field_id": "a", "charset_id": "digits_dot"},
        {"op": "contains_clause", "field_id": "a", "match_kind": "exact_text", "value": "URDG 758"},
    ]:
        assert validate(expression) == expression


@pytest.mark.parametrize(
    "expression, message",
    [
        ({"op": "sum", "args": []}, "unknown op"),
        ({"op": "all", "args": []}, "non-empty args"),
        ({"op": "any", "args": "x"}, "non-empty args"),
        ({"op": "exists", "field_id": ""}, "non-empty field_id"),
        ({"op": "exists", "field_id": "a", "extra": 1}, "does not accept"),
        ({"op": "not"}, "requires an arg"),
        ({"op": "compare", "left": FIELD, "comparator": "like", "right": LITERAL}, "comparator"),
        ({"op": "compare", "left": {"kind": "field"}, "comparator": "eq", "right": LITERAL}, "field operand"),
        ({"op": "compare", "left": FIELD, "comparator": "eq", "right": {"kind": "literal", "value_type": "money", "value": "1"}}, "literal type"),
        ({"op": "length", "field_id": "a", "unit": "byte"}, "requires an encoding"),
        ({"op": "length", "field_id": "a", "unit": "code_point", "encoding": "utf-8"}, "only allowed with unit=byte"),
        ({"op": "length", "field_id": "a", "unit": "code_point", "min": 5, "max": 2}, "must not exceed"),
        ({"op": "length", "field_id": "a", "unit": "code_point", "min": -1}, "non-negative"),
        ({"op": "charset", "field_id": "a", "charset_id": "^[A-Z]{3}$"}, "approved catalogue"),
        ({"op": "contains_clause", "field_id": "a", "match_kind": "regex", "value": "x"}, "exact_text"),
        ({"op": "contains_clause", "field_id": "a", "match_kind": "exact_text", "value": ""}, "non-empty value"),
    ],
)
def test_rejects_invalid_shapes(expression, message):
    with pytest.raises(RuleEvaluationError, match=message):
        validate(expression)


def test_rejects_regression_through_depth_limit():
    expression: dict = {"op": "exists", "field_id": "a"}
    for _ in range(9):
        expression = {"op": "not", "arg": expression}

    with pytest.raises(RuleEvaluationError, match="depth"):
        validate(expression)


def test_rejects_oversized_expressions():
    expression = {"op": "all", "args": [{"op": "exists", "field_id": f"f{index}"} for index in range(200)]}

    with pytest.raises(RuleEvaluationError, match="nodes"):
        validate(expression)