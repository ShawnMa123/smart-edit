"""Restricted, typed rule DSL evaluator (spec §4.2).

L1 slice implements only the deterministic subset needed for the synthetic rule:
`exists` and `compare`. Three-valued logic: `True` / `False` / `None` (unknown). A missing
fact is unknown — never "pass". No eval, no arbitrary code, no implicit conversions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    title: str
    domain: str
    severity: str
    gate_type: str
    target_operations: tuple[str, ...]
    applicability: dict
    required_facts: tuple[str, ...]
    expression: dict
    explanation: str


def _fact_state(facts: dict, field_id: str) -> str:
    fact = facts.get(field_id) or {}
    return fact.get("state", "missing")


def _fact_value(facts: dict, field_id: str):
    return (facts.get(field_id) or {}).get("value")


def evaluate(expression: dict, facts: dict) -> bool | None:
    """Evaluate one rule expression to True / False / None (unknown)."""
    op = expression.get("op")

    if op == "exists":
        state = _fact_state(facts, expression["field_id"])
        if state == "missing":
            return False
        if state == "unconfirmed":
            return None
        # confirmed: non-empty value counts as present
        value = _fact_value(facts, expression["field_id"])
        return value is not None and value != ""

    if op == "compare":
        left = _operand(expression["left"], facts)
        right = _operand(expression["right"], facts)
        if left is None or right is None:
            return None  # a missing field is unknown, not a mismatch
        comparator = expression["comparator"]
        return _compare(left, right, comparator)

    raise ValueError(f"unsupported op: {op!r}")


def _operand(operand: dict, facts: dict):
    if operand.get("kind") == "field":
        return _fact_value(facts, operand["field_id"])
    if operand.get("kind") == "literal":
        return _coerce(operand["value"], operand.get("value_type", "string"))
    raise ValueError(f"unsupported operand kind: {operand.get('kind')!r}")


def _coerce(value: str, value_type: str):
    if value_type == "decimal":
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None
    return value  # string / date / datetime / boolean pass through


def _compare(left, right, comparator: str) -> bool | None:
    # No implicit conversion (spec §4.2): incompatible types are unknown, never a mismatch.
    if type(left) is not type(right):
        return None
    if comparator == "eq":
        return left == right
    if comparator == "ne":
        return left != right
    if comparator == "lt":
        return left < right
    if comparator == "le":
        return left <= right
    if comparator == "gt":
        return left > right
    if comparator == "ge":
        return left >= right
    raise ValueError(f"unsupported comparator: {comparator!r}")
