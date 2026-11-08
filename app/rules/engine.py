"""Three-valued rule evaluation (AI-audit §5.1-5.3).

Pure by construction: it takes bound values and a context dict and returns verdicts. No model, no
network, no filesystem writes — `tests/test_rule_engine.py` asserts that.

Reason codes are part of the contract: `needs_input` and `unable_to_assess` must be explainable, and
`unknown` is never allowed to become `pass`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.audit.bind import ABSENT, CONFIRMED, UNCONFIRMED, VIOLATION, AuditValue
from app.parsing.normalize import normalize_ws
from app.rules.schema import CATALOGUE_ALLOWED, FieldSchema, SchemaBundle
from app.rules.types import (
    FAILED,
    FINDING,
    NEEDS_INPUT,
    NOT_APPLICABLE,
    PASS,
    UNABLE_TO_ASSESS,
    CheckResult,
    RuleEvaluationError,
    Tri,
    Unit,
)

# Reasons that mean "a human has to supply or confirm something".
_INPUT_REASONS = frozenset({"unconfirmed", "value_violation", "absent"})
# Operations a schema/technical violation blocks (AI-audit §7.2).
HARD_BLOCK_OPERATIONS = ("start_approval", "formal_export", "handoff", "formal_mapping")


def _status_for_reason(reason: str | None) -> str:
    return NEEDS_INPUT if reason in _INPUT_REASONS else UNABLE_TO_ASSESS


def _field_type(context: dict | None, field_id: str) -> str | None:
    """Look the field's declared type up in the context's schema, if a schema was supplied."""
    schema = (context or {}).get("schema")
    if schema is None:
        return None
    fields = getattr(schema, "fields", schema)
    field = fields.get(field_id) if isinstance(fields, dict) else None
    return getattr(field, "value_type", None)


# Field values live as normalized strings; comparison needs the declared type, never an implicit cast.
_TYPED_COERCERS = {
    "amount": Decimal,
    "integer": int,
    "date": date.fromisoformat,
    "currency": str,
    "country": str,
    "string": str,
}


def _resolve_operand(
    operand: dict, values: dict[str, AuditValue], context: dict | None = None
) -> tuple[object, Tri, str | None]:
    if operand["kind"] == "field":
        field_id = operand["field_id"]
        bound = values.get(field_id) or AuditValue(field_id, ABSENT)
        if bound.state != CONFIRMED or bound.value is None:
            if bound.state == UNCONFIRMED:
                return None, Tri.UNKNOWN, "unconfirmed"
            if bound.state == ABSENT:
                return None, Tri.UNKNOWN, "absent"
            return None, Tri.UNKNOWN, "value_violation"

        coercer = _TYPED_COERCERS.get(_field_type(context, field_id) or "")
        if coercer is None:
            return bound.value, Tri.TRUE, None
        try:
            return coercer(bound.value), Tri.TRUE, None
        except (ValueError, TypeError, ArithmeticError, InvalidOperation):
            # The *document* value does not parse as its declared type. The schema check already reports
            # it as a finding; the rule simply cannot judge it. This is a document problem.
            return None, Tri.UNKNOWN, "value_unparsable"

    kind, raw = operand["value_type"], operand["value"]
    try:
        if kind == "decimal":
            return Decimal(str(raw)), Tri.TRUE, None
        if kind == "date":
            return date.fromisoformat(str(raw)), Tri.TRUE, None
        if kind == "datetime":
            return datetime.fromisoformat(str(raw)), Tri.TRUE, None
        if kind == "boolean":
            return bool(raw), Tri.TRUE, None
        return str(raw), Tri.TRUE, None
    except (InvalidOperation, ValueError):
        raise RuleEvaluationError(f"literal {raw!r} is not a valid {kind}") from None


def _comparable(left: object, right: object) -> bool:
    """Exact type match, plus numeric promotion.

    `datetime` subclasses `date` and `bool` subclasses `int`, so a naive isinstance check would happily
    "compare" a date field with a datetime literal (and then crash inside the comparison). Exact types keep
    that a rule-authoring error — but `integer` vs `decimal` must stay comparable, because the bundle
    validator explicitly allows it (`LITERAL_COMPATIBILITY`).
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    numeric = (int, Decimal)
    if isinstance(left, numeric) and isinstance(right, numeric):
        return True
    if type(left) is not type(right):
        return False
    return isinstance(left, (Decimal, date, datetime, str))


def _compare(comparator: str, left: object, right: object) -> bool:
    if comparator == "eq":
        return left == right
    if comparator == "ne":
        return left != right
    if isinstance(left, bool) or isinstance(right, bool):
        raise RuleEvaluationError(f"comparator {comparator!r} is not defined for booleans")
    if isinstance(left, (int, Decimal)) and isinstance(right, (int, Decimal)):
        # integer fields compare as exact decimals; never through float.
        left, right = Decimal(left), Decimal(right)
    if comparator == "lt":
        return left < right  # type: ignore[operator]
    if comparator == "le":
        return left <= right  # type: ignore[operator]
    if comparator == "gt":
        return left > right  # type: ignore[operator]
    return left >= right  # type: ignore[operator]


def evaluate_expression(
    expression: dict,
    values: dict[str, AuditValue],
    context: dict | None = None,
) -> tuple[Tri, str | None]:
    """Evaluate one expression tree. Returns `(tri, reason)`; `reason` is set when tri is UNKNOWN."""
    op = expression["op"]
    context = context or {}

    if op == "all":
        reason: str | None = None
        for arg in expression["args"]:
            tri, arg_reason = evaluate_expression(arg, values, context)
            if tri is Tri.FALSE:
                return Tri.FALSE, None
            if tri is Tri.UNKNOWN and reason is None:
                reason = arg_reason
        return (Tri.UNKNOWN, reason) if reason else (Tri.TRUE, None)

    if op == "any":
        reason = None
        for arg in expression["args"]:
            tri, arg_reason = evaluate_expression(arg, values, context)
            if tri is Tri.TRUE:
                return Tri.TRUE, None
            if tri is Tri.UNKNOWN and reason is None:
                reason = arg_reason
        return (Tri.UNKNOWN, reason) if reason else (Tri.FALSE, None)

    if op == "not":
        tri, reason = evaluate_expression(expression["arg"], values, context)
        if tri is Tri.UNKNOWN:
            return Tri.UNKNOWN, reason
        return (Tri.FALSE if tri is Tri.TRUE else Tri.TRUE), None

    if op == "exists":
        bound = values.get(expression["field_id"]) or AuditValue(expression["field_id"], ABSENT)
        if bound.state == CONFIRMED and bound.value not in (None, ""):
            return Tri.TRUE, None
        if bound.state == ABSENT:
            return Tri.FALSE, None
        return Tri.UNKNOWN, ("unconfirmed" if bound.state == UNCONFIRMED else "value_violation")

    if op == "compare":
        left, left_tri, left_reason = _resolve_operand(expression["left"], values, context)
        right, right_tri, right_reason = _resolve_operand(expression["right"], values, context)
        if left_tri is not Tri.TRUE:
            return Tri.UNKNOWN, left_reason
        if right_tri is not Tri.TRUE:
            return Tri.UNKNOWN, right_reason
        if not _comparable(left, right):
            # No implicit conversion, and this is a *rule authoring* problem, not a document problem:
            # `validate_against_schema()` refuses it at load time, and if one slips through the unit
            # fails loudly instead of quietly becoming "unable to assess".
            return Tri.UNKNOWN, "rule_type_mismatch"
        return (Tri.TRUE if _compare(expression["comparator"], left, right) else Tri.FALSE), None

    if op == "length":
        return _evaluate_length(expression, values)

    if op == "charset":
        bound = values.get(expression["field_id"]) or AuditValue(expression["field_id"], ABSENT)
        if bound.state != CONFIRMED or bound.value is None:
            return Tri.UNKNOWN, ("unconfirmed" if bound.state == UNCONFIRMED else "absent")
        allowed = set(CATALOGUE_ALLOWED[expression["charset_id"]])
        return (Tri.TRUE if set(bound.value) <= allowed else Tri.FALSE), None

    if op == "contains_clause":
        bound = values.get(expression["field_id"]) or AuditValue(expression["field_id"], ABSENT)
        if bound.state != CONFIRMED or bound.value is None:
            return Tri.UNKNOWN, ("unconfirmed" if bound.state == UNCONFIRMED else "absent")
        needle = normalize_ws(expression["value"])
        return (Tri.TRUE if needle in normalize_ws(bound.value) else Tri.FALSE), None

    raise RuleEvaluationError(f"unhandled op {op!r}")


def _evaluate_length(expression: dict, values: dict[str, AuditValue]) -> tuple[Tri, str | None]:
    bound = values.get(expression["field_id"]) or AuditValue(expression["field_id"], ABSENT)
    if bound.state != CONFIRMED or bound.value is None:
        return Tri.UNKNOWN, ("unconfirmed" if bound.state == UNCONFIRMED else "absent")

    unit = expression["unit"]
    if unit == "code_point":
        size = len(bound.value)
    elif unit == "byte":
        try:
            size = len(bound.value.encode(expression["encoding"]))
        except (UnicodeEncodeError, LookupError):
            # An encoding failure is a failure, never "length zero".
            raise RuleEvaluationError("encoding_failed") from None
    else:
        # Grapheme clusters need a segmentation library this build does not ship; refusing is honest.
        raise RuleEvaluationError("unsupported_unit")

    minimum, maximum = expression.get("min"), expression.get("max")
    if minimum is not None and size < minimum:
        return Tri.FALSE, None
    if maximum is not None and size > maximum:
        return Tri.FALSE, None
    return Tri.TRUE, None


# ---------------------------------------------------------------------------
# One rule, and one schema check
# ---------------------------------------------------------------------------


def _rule_ref(rule: dict) -> dict:
    return {"rule_id": rule["rule_id"], "version": rule["version"]}


def _finding_for(rule: dict, field_id: str | None, evidence: str | None) -> dict:
    return {
        "rule_ref": _rule_ref(rule),
        "title": rule.get("title", rule["rule_id"]),
        "severity": rule.get("severity", "warn"),
        "gate_type": rule.get("gate_type", "advisory"),
        "target_operations": list(rule.get("target_operations") or ()),
        "category": rule.get("category", "field"),
        "field_id": field_id,
        "evidence": evidence,
    }


def evaluate_rule(rule: dict, values: dict[str, AuditValue], context: dict | None = None) -> CheckResult:
    """Applicability first, then the expression (design D5). `unknown` never becomes `pass`."""
    check_id = f"RULE:{rule['rule_id']}@{rule['version']}"
    field_id = rule.get("field_id")
    try:
        applicability = rule.get("applicability")
        if applicability is not None:
            tri, reason = evaluate_expression(applicability, values, context)
            if tri is Tri.FALSE:
                return CheckResult(check_id, NOT_APPLICABLE, reason_code="not_applicable")
            if tri is Tri.UNKNOWN:
                if reason == "rule_type_mismatch":
                    return CheckResult(check_id, FAILED, reason_code=reason)
                return CheckResult(check_id, _status_for_reason(reason), reason_code=reason)

        tri, reason = evaluate_expression(rule["expression"], values, context)
        if tri is Tri.TRUE:
            return CheckResult(check_id, PASS)
        if tri is Tri.FALSE:
            evidence = values[field_id].value if field_id and field_id in values else None
            return CheckResult(
                check_id, FINDING, finding=_finding_for(rule, field_id, evidence), detail={"reason": "violated"}
            )
        if reason == "rule_type_mismatch":
            return CheckResult(check_id, FAILED, reason_code=reason)
        return CheckResult(check_id, _status_for_reason(reason), reason_code=reason)
    except RuleEvaluationError as exc:
        return CheckResult(check_id, FAILED, reason_code=str(exc))


_SCHEMA_RULES = {
    "required": {"severity": "critical", "gate_type": "hard_block", "title": "Required field is missing"},
    "type": {"severity": "critical", "gate_type": "hard_block", "title": "Value does not match its type"},
    "max_length": {"severity": "warn", "gate_type": "hard_block", "title": "Value is longer than allowed"},
    "charset": {"severity": "warn", "gate_type": "hard_block", "title": "Value uses characters outside the allowed set"},
}

_TYPED_PARSERS = {
    "amount": lambda raw: Decimal(raw),
    "integer": lambda raw: int(raw),
    "date": lambda raw: date.fromisoformat(raw),
    "string": lambda raw: raw,
    "currency": lambda raw: raw if len(raw) == 3 and raw.isalpha() and raw.isupper() else (_ for _ in ()).throw(ValueError("currency")),
    "country": lambda raw: raw if len(raw) == 2 and raw.isalpha() and raw.isupper() else (_ for _ in ()).throw(ValueError("country")),
}


def evaluate_schema_check(
    unit: Unit,
    field: FieldSchema,
    value: AuditValue,
    schema_version: str,
) -> CheckResult:
    """Evaluate one schema unit (`SCHEMA:<field>:<aspect>`).

    `required` is the only aspect that produces a finding for an absent value; the technical aspects
    become `not_applicable` instead of pretending to pass (AUD-02/03/06).
    """
    aspect = unit.check_id.rsplit(":", 1)[-1]
    meta = _SCHEMA_RULES.get(aspect)
    if meta is None:
        return CheckResult(unit.check_id, FAILED, reason_code="unknown_schema_aspect")
    finding = {
        "rule_ref": {"rule_id": f"SCHEMA:{field.field_id}:{aspect}", "version": schema_version},
        "title": meta["title"],
        "severity": meta["severity"],
        "gate_type": meta["gate_type"],
        "target_operations": list(HARD_BLOCK_OPERATIONS),
        "category": "field",
        "field_id": field.field_id,
        "evidence": value.value,
    }

    if aspect == "required":
        if value.state == ABSENT:
            return CheckResult(unit.check_id, FINDING, finding=finding, detail={"reason": "required_missing"})
        if value.state == UNCONFIRMED:
            return CheckResult(unit.check_id, NEEDS_INPUT, reason_code="unconfirmed")
        if value.state == VIOLATION:
            return CheckResult(unit.check_id, FAILED, reason_code="value_violation")
        return CheckResult(unit.check_id, PASS)

    if value.state == ABSENT:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="absent_optional")
    if value.state == UNCONFIRMED:
        return CheckResult(unit.check_id, NEEDS_INPUT, reason_code="unconfirmed")
    if value.state == VIOLATION or value.value is None:
        return CheckResult(unit.check_id, FAILED, reason_code="value_violation")

    if aspect == "type":
        parser = _TYPED_PARSERS.get(field.value_type)
        if parser is None:  # pragma: no cover - guarded by schema.build_schema
            return CheckResult(unit.check_id, FAILED, reason_code="unsupported_type")
        try:
            parser(value.value)
        except (ValueError, ArithmeticError, InvalidOperation):
            return CheckResult(unit.check_id, FINDING, finding=finding, detail={"reason": "invalid_value"})
        return CheckResult(unit.check_id, PASS)

    if aspect == "max_length":
        if field.max_length is not None and len(value.value) > field.max_length:
            return CheckResult(unit.check_id, FINDING, finding=finding, detail={"reason": "too_long"})
        return CheckResult(unit.check_id, PASS)

    # charset
    if field.charset_id is None:  # pragma: no cover - planner only emits units for declared sets
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_charset")
    allowed = set(CATALOGUE_ALLOWED[field.charset_id])
    if not set(value.value) <= allowed:
        return CheckResult(unit.check_id, FINDING, finding=finding, detail={"reason": "charset"})
    return CheckResult(unit.check_id, PASS)