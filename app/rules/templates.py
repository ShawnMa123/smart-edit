"""Versioned template packs: the customer's expectations as data (design D14-D16).

A rule bundle is executable expressions; a template is *where the expectations come from* — the values a
customer will not accept differently ("the settlement currency MUST be USD", "the origin country MUST be
one of these"), the clauses they insist on, and the declarations they require. Templates never inline DSL:
a field expectation is **compiled** onto the closed op set (D15) so one engine evaluates both, and template
fields are merged into an effective schema (D16) instead of being pushed into `fields.yaml`.

Nothing here imports a model or an HTTP client — `tests/test_rule_engine.py` enforces that for the whole
kernel, and AT-01 depends on it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.rules.bundles import LITERAL_COMPATIBILITY
from app.rules.dsl import validate as validate_expression
from app.rules.engine import HARD_BLOCK_OPERATIONS
from app.rules.schema import VALUE_TYPES, FieldSchema, SchemaBundle
from app.rules.types import RuleEvaluationError

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

# `required` = must be present, `controlled` = must match the controlled text exactly,
# `optional` = present or absent both acceptable, `semantic_equivalent` = needs a model (not this build).
CLAUSE_REQUIREMENTS = ("required", "controlled", "optional", "semantic_equivalent")
GATE_TYPES = ("advisory", "human_review", "hard_block")
# `allowed_values` compares text; typed literals for amounts/dates are a later change, refused at load.
STRING_LIKE_TYPES = ("string", "currency", "country")
SEVERITY_BY_GATE = {"hard_block": "critical", "human_review": "warn", "advisory": "warn"}


class TemplateError(ValueError):
    """A template pack is malformed, contradicts the schema, or contradicts another pack."""


@dataclass(frozen=True)
class FieldExpectation:
    """One value the customer will not accept differently."""

    field_id: str
    gate_type: str
    severity: str
    value_type: str | None = None  # required only when the field is not in `fields.yaml`
    allowed_values: tuple[str, ...] = ()
    required: bool = False
    required_when: dict | None = None


@dataclass(frozen=True)
class ClauseRequirement:
    clause_id: str
    requirement: str
    text: str
    gate_type: str
    severity: str


@dataclass(frozen=True)
class DeclarationRequirement:
    """An internal-policy declaration: judged by presence only, never by what it implies (AUD-11)."""

    declaration_id: str
    text: str
    gate_type: str
    severity: str
    waivable: bool = False


@dataclass(frozen=True)
class TemplatePack:
    template_id: str
    version: str
    published: bool
    synthetic: bool
    content_sha256: str
    document_types: tuple[str, ...]
    counterparty_name: str | None
    counterparty_field: str
    counterparty_match: str
    fields: tuple[FieldExpectation, ...]
    clauses: tuple[ClauseRequirement, ...]
    declarations: tuple[DeclarationRequirement, ...]
    policy_packs: tuple[str, ...]
    body: str | None


def _digest(payload: object) -> str:
    """Same 12-hex convention as rule bundles, so both fit one report."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _require(payload: dict, key: str, where: str) -> object:
    if key not in payload:
        raise TemplateError(f"{where}: missing {key}")
    return payload[key]


def _gate_type(raw: object, where: str) -> str:
    if raw not in GATE_TYPES:
        raise TemplateError(f"{where}: gate_type {raw!r} not in {GATE_TYPES}")
    return str(raw)


def _severity(raw: object, gate_type: str, where: str) -> str:
    if raw is None:
        return SEVERITY_BY_GATE[gate_type]
    if raw not in ("critical", "warn", "info"):
        raise TemplateError(f"{where}: severity {raw!r} not in ('critical', 'warn', 'info')")
    return str(raw)


def _field_expectation(raw: object, where: str) -> FieldExpectation:
    if not isinstance(raw, dict):
        raise TemplateError(f"{where}: field expectation must be a mapping")
    field_id = str(_require(raw, "key", where))
    gate_type = _gate_type(raw.get("gate_type", "hard_block"), where)
    allowed = tuple(str(value) for value in (raw.get("allowed_values") or ()))
    value_type = raw.get("type")
    if value_type is not None and value_type not in VALUE_TYPES:
        raise TemplateError(f"{where}: field {field_id!r} has unsupported type {value_type!r}")
    required_when = raw.get("required_when")
    if required_when is not None and not isinstance(required_when, dict):
        raise TemplateError(f"{where}: field {field_id!r} required_when must be a mapping")
    if not allowed and not raw.get("required") and required_when is None:
        raise TemplateError(f"{where}: field {field_id!r} declares no expectation")
    return FieldExpectation(
        field_id=field_id,
        gate_type=gate_type,
        severity=_severity(raw.get("severity"), gate_type, where),
        value_type=str(value_type) if value_type is not None else None,
        allowed_values=allowed,
        required=bool(raw.get("required", False)),
        required_when=dict(required_when) if required_when else None,
    )


def _clause(raw: object, where: str) -> ClauseRequirement:
    if not isinstance(raw, dict):
        raise TemplateError(f"{where}: clause must be a mapping")
    clause_id = str(_require(raw, "clause_id", where))
    requirement = str(_require(raw, "requirement", where))
    if requirement not in CLAUSE_REQUIREMENTS:
        raise TemplateError(
            f"{where}/{clause_id}: requirement {requirement!r} not in {CLAUSE_REQUIREMENTS}"
        )
    text = str(_require(raw, "text", where)).strip()
    if not text:
        raise TemplateError(f"{where}/{clause_id}: clause text is empty")
    gate_type = _gate_type(raw.get("gate_type", "hard_block"), f"{where}/{clause_id}")
    return ClauseRequirement(
        clause_id=clause_id,
        requirement=requirement,
        text=text,
        gate_type=gate_type,
        severity=_severity(raw.get("severity"), gate_type, f"{where}/{clause_id}"),
    )


def _declaration(raw: object, where: str) -> DeclarationRequirement:
    if not isinstance(raw, dict):
        raise TemplateError(f"{where}: internal_policy entry must be a mapping")
    declaration_id = str(_require(raw, "declaration_id", where))
    text = str(_require(raw, "text", where)).strip()
    if not text:
        raise TemplateError(f"{where}/{declaration_id}: declaration text is empty")
    gate_type = _gate_type(raw.get("gate_type", "human_review"), f"{where}/{declaration_id}")
    return DeclarationRequirement(
        declaration_id=declaration_id,
        text=text,
        gate_type=gate_type,
        severity=_severity(raw.get("severity"), gate_type, f"{where}/{declaration_id}"),
        waivable=bool(raw.get("waivable", False)),
    )


def _counterparty(raw: object, where: str) -> tuple[str | None, str, str]:
    if raw is None:
        return None, "beneficiary_name", "exact_normalized"
    if not isinstance(raw, dict):
        raise TemplateError(f"{where}: counterparty must be a mapping")
    match = str(raw.get("match") or "exact_normalized")
    if match != "exact_normalized":
        raise TemplateError(f"{where}: counterparty.match {match!r} is not supported")
    name = raw.get("name")
    return (str(name) if name else None), str(raw.get("field") or "beneficiary_name"), match


def load_template(path: Path) -> TemplatePack:
    """Load one pack and stamp its `content_sha256`."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TemplateError(f"{path.name}: template must be a mapping")
    where = path.name
    template_id = str(_require(payload, "template_id", where))
    version = str(_require(payload, "version", where))
    published = bool(_require(payload, "published", where))
    document_types = tuple(str(item) for item in (payload.get("document_types") or ("guarantee",)))
    counterparty_name, counterparty_field, counterparty_match = _counterparty(
        payload.get("counterparty"), where
    )

    fields = tuple(_field_expectation(raw, where) for raw in payload.get("fields") or ())
    clauses = tuple(_clause(raw, where) for raw in payload.get("clauses") or ())
    declarations = tuple(_declaration(raw, where) for raw in payload.get("internal_policy") or ())
    policy_packs = tuple(str(item) for item in payload.get("policy_packs") or ())
    if not (fields or clauses or declarations):
        raise TemplateError(f"{where}: template declares no expectation at all")

    body = payload.get("body")
    fingerprint = {
        "template_id": template_id,
        "version": version,
        "document_types": list(document_types),
        "counterparty": {
            "name": counterparty_name,
            "field": counterparty_field,
            "match": counterparty_match,
        },
        "fields": [vars(item) for item in fields],
        "clauses": [vars(item) for item in clauses],
        "declarations": [vars(item) for item in declarations],
        "policy_packs": list(policy_packs),
        "body": body,
    }
    return TemplatePack(
        template_id=template_id,
        version=version,
        published=published,
        synthetic=bool(payload.get("synthetic", False)),
        content_sha256=_digest(fingerprint),
        document_types=document_types,
        counterparty_name=counterparty_name,
        counterparty_field=counterparty_field,
        counterparty_match=counterparty_match,
        fields=fields,
        clauses=clauses,
        declarations=declarations,
        policy_packs=policy_packs,
        body=str(body) if body else None,
    )


def load_templates(
    directory: str | Path | None = None, *, include_unpublished: bool = False
) -> list[TemplatePack]:
    """Load every pack in `directory`; unpublished versions are skipped, never evaluated."""
    root = Path(directory) if directory is not None else TEMPLATE_DIR
    if not root.exists():
        return []
    packs: list[TemplatePack] = []
    for path in sorted(root.glob("*.yaml")):
        pack = load_template(path)
        if include_unpublished or pack.published:
            packs.append(pack)
    return packs


def merge_schema(base: SchemaBundle, templates=()) -> SchemaBundle:
    """Union of the field dictionary and whatever the templates introduce (design D16).

    A template field that is *not* in `fields.yaml` must declare its type; a type that contradicts the
    dictionary is a load-time error, never a silent choice between the two.
    """
    merged = dict(base.fields)
    for template in templates:
        for expectation in template.fields:
            existing = merged.get(expectation.field_id)
            if existing is not None:
                if expectation.value_type and expectation.value_type != existing.value_type:
                    raise TemplateError(
                        f"{template.template_id}/{expectation.field_id}: template type "
                        f"{expectation.value_type!r} contradicts the schema type "
                        f"{existing.value_type!r}"
                    )
                continue
            if expectation.value_type is None:
                raise TemplateError(
                    f"{template.template_id}/{expectation.field_id}: field is not in the schema and the "
                    f"template does not declare its type"
                )
            merged[expectation.field_id] = FieldSchema(
                field_id=expectation.field_id,
                value_type=expectation.value_type,
                required=False,
            )
    return SchemaBundle(version=base.version, fields=merged)


def _literal_type(value_type: str) -> str:
    """The literal kind a field of `value_type` may be compared with (mirrors `LITERAL_COMPATIBILITY`)."""
    allowed = sorted(LITERAL_COMPATIBILITY[value_type])
    return allowed[0]


def _compare(field_id: str, value: str, value_type: str) -> dict:
    return {
        "op": "compare",
        "left": {"kind": "field", "field_id": field_id},
        "comparator": "eq",
        "right": {"kind": "literal", "value_type": value_type, "value": value},
    }


def _expression_for(expectation: FieldExpectation, schema_value_type: str, where: str) -> dict:
    """Compile one expectation onto the closed op set (design D15).

    `allowed_values` becomes `compare`/`any`, a required field becomes `exists`, and a field that is both
    required and restricted becomes `all(exists, …)` so an absent value is a *finding*, not "unknown".
    """
    parts: list[dict] = []
    if expectation.required or expectation.required_when:
        # `required_when` is "required if the condition holds": the condition goes to `applicability`,
        # the presence check stays in `expression` (design D5, §5.1).
        parts.append({"op": "exists", "field_id": expectation.field_id})
    if expectation.allowed_values:
        if schema_value_type not in STRING_LIKE_TYPES:
            raise TemplateError(
                f"{where}: allowed_values on field {expectation.field_id!r} ({schema_value_type}) is not "
                f"supported; only {STRING_LIKE_TYPES} compare as text in this build"
            )
        comparisons = [_compare(expectation.field_id, value, "string") for value in expectation.allowed_values]
        parts.append(comparisons[0] if len(comparisons) == 1 else {"op": "any", "args": comparisons})
    if not parts:  # pragma: no cover - the loader refuses an expectation with nothing to check
        raise TemplateError(f"{where}: field {expectation.field_id!r} declares no expectation")
    return parts[0] if len(parts) == 1 else {"op": "all", "args": parts}


def _applicability(expectation: FieldExpectation, schema: SchemaBundle, where: str) -> dict | None:
    if not expectation.required_when:
        return None
    condition = expectation.required_when
    field_id = str(condition.get("field_id") or "")
    if field_id not in schema.fields:
        raise TemplateError(f"{where}: required_when references unknown field {field_id!r}")
    if "equals" not in condition:
        raise TemplateError(f"{where}: required_when on {expectation.field_id!r} needs `equals`")
    literal_type = _literal_type(schema.fields[field_id].value_type)
    return _compare(field_id, str(condition["equals"]), literal_type)


def compile_expectations(template: TemplatePack, schema: SchemaBundle) -> list[dict]:
    """Turn the template's field expectations into rules the existing engine can evaluate.

    The compiled rule is shaped exactly like a hand-written bundle rule, so `evaluate_rule()`,
    `validate_against_schema()` and the vector gate apply without a second code path.
    """
    rules: list[dict] = []
    for expectation in template.fields:
        where = f"{template.template_id}/fields/{expectation.field_id}"
        declared = schema.fields.get(expectation.field_id)
        if declared is None:
            raise TemplateError(
                f"{where}: field is not in the effective schema; declare its `type` in the template"
            )
        rule = {
            "rule_id": f"TEMPLATE:{template.template_id}:{expectation.field_id}",
            "version": template.version,
            "title": _title_for(expectation),
            "category": "field",
            "severity": expectation.severity,
            "gate_type": expectation.gate_type,
            "target_operations": (
                list(HARD_BLOCK_OPERATIONS) if expectation.gate_type == "hard_block" else []
            ),
            "field_id": expectation.field_id,
            "template_id": template.template_id,
            "expression": _expression_for(expectation, declared.value_type, where),
        }
        applicability = _applicability(expectation, schema, where)
        if applicability is not None:
            rule["applicability"] = applicability
        try:
            validate_expression(rule["expression"])
            if applicability is not None:
                validate_expression(applicability)
        except RuleEvaluationError as exc:
            raise TemplateError(f"{where}: {exc}") from exc
        rules.append(rule)
    return rules


def _title_for(expectation: FieldExpectation) -> str:
    if expectation.allowed_values:
        allowed = ", ".join(expectation.allowed_values)
        return f"{expectation.field_id} must be one of: {allowed}"
    if expectation.required_when:
        condition = expectation.required_when
        return (
            f"{expectation.field_id} is required when {condition.get('field_id')} "
            f"is {condition.get('equals')}"
        )
    return f"{expectation.field_id} is required"
    return str(raw)