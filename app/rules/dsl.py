"""The closed, typed rule DSL (AI-audit §5.2).

Only these ops exist; there are no scripts, no user regular expressions, no network and no model. A
bundle that violates the shape is rejected at load time, not at evaluation time.
"""

from __future__ import annotations

from app.rules.schema import CATALOGUE_ALLOWED
from app.rules.types import RuleEvaluationError

OPS = (
    "all",
    "any",
    "not",
    "exists",
    "compare",
    "length",
    "charset",
    "contains_clause",
)
COMPARATORS = ("eq", "ne", "lt", "le", "gt", "ge")
LENGTH_UNITS = ("code_point", "grapheme", "byte")
LITERAL_TYPES = ("string", "decimal", "date", "datetime", "boolean")

MAX_DEPTH = 8
MAX_NODES = 200

_ALLOWED_KEYS = {
    "all": {"op", "args"},
    "any": {"op", "args"},
    "not": {"op", "arg"},
    "exists": {"op", "field_id"},
    "compare": {"op", "left", "comparator", "right"},
    "length": {"op", "field_id", "unit", "min", "max", "encoding"},
    "charset": {"op", "field_id", "charset_id"},
    "contains_clause": {"op", "field_id", "match_kind", "value"},
}


def validate_operand(operand: object) -> dict:
    if not isinstance(operand, dict):
        raise RuleEvaluationError(f"operand must be a mapping, got {type(operand).__name__}")
    kind = operand.get("kind")
    if kind == "field":
        if set(operand) != {"kind", "field_id"} or not isinstance(operand.get("field_id"), str):
            raise RuleEvaluationError(f"field operand must be {{kind, field_id}}: {operand!r}")
        return operand
    if kind == "literal":
        if set(operand) != {"kind", "value_type", "value"}:
            raise RuleEvaluationError(f"literal operand must be {{kind, value_type, value}}: {operand!r}")
        if operand["value_type"] not in LITERAL_TYPES:
            raise RuleEvaluationError(f"unsupported literal type {operand['value_type']!r}")
        return operand
    raise RuleEvaluationError(f"unknown operand kind {kind!r}")


def validate(expression: object, *, _depth: int = 1, _counter: list[int] | None = None) -> dict:
    """Validate one expression tree; raises `RuleEvaluationError` on the first violation."""
    counter = _counter if _counter is not None else [0]
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise RuleEvaluationError(f"expression exceeds {MAX_NODES} nodes")
    if _depth > MAX_DEPTH:
        raise RuleEvaluationError(f"expression exceeds depth {MAX_DEPTH}")
    if not isinstance(expression, dict):
        raise RuleEvaluationError(f"expression must be a mapping, got {type(expression).__name__}")

    op = expression.get("op")
    if op not in OPS:
        raise RuleEvaluationError(f"unknown op {op!r}")
    extra = set(expression) - _ALLOWED_KEYS[op]
    if extra:
        raise RuleEvaluationError(f"op {op!r} does not accept {sorted(extra)}")

    if op in ("all", "any"):
        args = expression.get("args")
        if not isinstance(args, list) or not args:
            raise RuleEvaluationError(f"{op} requires a non-empty args list")
        for arg in args:
            validate(arg, _depth=_depth + 1, _counter=counter)
        return expression

    if op == "not":
        if "arg" not in expression:
            raise RuleEvaluationError("not requires an arg")
        validate(expression["arg"], _depth=_depth + 1, _counter=counter)
        return expression

    if op == "exists":
        _require_field(expression, op)
        return expression

    if op == "compare":
        if expression.get("comparator") not in COMPARATORS:
            raise RuleEvaluationError(f"compare requires comparator in {COMPARATORS}")
        validate_operand(expression.get("left"))
        validate_operand(expression.get("right"))
        return expression

    if op == "length":
        _require_field(expression, op)
        unit = expression.get("unit")
        if unit not in LENGTH_UNITS:
            raise RuleEvaluationError(f"length requires unit in {LENGTH_UNITS}")
        if unit == "byte" and not expression.get("encoding"):
            raise RuleEvaluationError("byte length requires an encoding")
        if unit != "byte" and expression.get("encoding"):
            raise RuleEvaluationError("encoding is only allowed with unit=byte")
        minimum, maximum = expression.get("min"), expression.get("max")
        for name, bound in (("min", minimum), ("max", maximum)):
            if bound is not None and (not isinstance(bound, int) or bound < 0):
                raise RuleEvaluationError(f"length.{name} must be a non-negative integer")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise RuleEvaluationError("length.min must not exceed length.max")
        return expression

    if op == "charset":
        _require_field(expression, op)
        if expression.get("charset_id") not in CATALOGUE_ALLOWED:
            raise RuleEvaluationError(
                f"charset_id must come from the approved catalogue {sorted(CATALOGUE_ALLOWED)}"
            )
        return expression

    # contains_clause
    _require_field(expression, op)
    if expression.get("match_kind") != "exact_text":
        raise RuleEvaluationError("contains_clause supports match_kind='exact_text' only")
    if not isinstance(expression.get("value"), str) or not expression["value"]:
        raise RuleEvaluationError("contains_clause requires a non-empty value")
    return expression


def _require_field(expression: dict, op: str) -> None:
    if not isinstance(expression.get("field_id"), str) or not expression["field_id"]:
        raise RuleEvaluationError(f"{op} requires a non-empty field_id")