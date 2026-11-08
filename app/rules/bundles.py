"""Versioned rule bundles (design D4).

A bundle is data, not code: it is hashed, versioned, and only `published` bundles are evaluated. Integrity
problems are reported, never silently skipped — a missing mandatory bundle must not read as "no problems".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.rules.dsl import validate
from app.rules.types import RuleEvaluationError

BUNDLE_DIR = Path(__file__).resolve().parent / "bundles"

REQUIRED_RULE_KEYS = ("rule_id", "version", "title", "severity", "gate_type", "expression")
VALID_SEVERITIES = ("critical", "warn", "info")
VALID_GATE_TYPES = ("advisory", "human_review", "hard_block")


class BundleError(ValueError):
    """A bundle is malformed or contradicts another bundle."""


@dataclass(frozen=True)
class RuleBundle:
    bundle_id: str
    version: str
    published: bool
    content_sha256: str
    document_types: tuple[str, ...]
    rules: tuple[dict, ...]
    # Policy-pack metadata (design D19): needed to list the resolved policy in the report. Optional, so
    # an existing bundle file keeps loading unchanged.
    owner: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    source: str | None = None


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _validate_rule(rule: object, where: str) -> dict:
    if not isinstance(rule, dict):
        raise BundleError(f"{where}: rule must be a mapping")
    missing = [key for key in REQUIRED_RULE_KEYS if key not in rule]
    if missing:
        raise BundleError(f"{where}: rule is missing {missing}")
    if rule["severity"] not in VALID_SEVERITIES:
        raise BundleError(f"{where}: severity {rule['severity']!r} not in {VALID_SEVERITIES}")
    if rule["gate_type"] not in VALID_GATE_TYPES:
        raise BundleError(f"{where}: gate_type {rule['gate_type']!r} not in {VALID_GATE_TYPES}")
    if rule["gate_type"] == "hard_block" and rule.get("method") == "semantic":
        raise BundleError(f"{where}: a semantic rule can never be hard_block")
    try:
        validate(rule["expression"])
        if rule.get("applicability") is not None:
            validate(rule["applicability"])
    except RuleEvaluationError as exc:
        raise BundleError(f"{where}: {exc}") from exc
    return rule


def load_bundle(path: Path) -> RuleBundle:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BundleError(f"{path.name}: bundle must be a mapping")

    for key in ("bundle_id", "version", "published", "rules"):
        if key not in payload:
            raise BundleError(f"{path.name}: missing {key}")

    rules = tuple(
        _validate_rule(rule, f"{path.name}[{index}]") for index, rule in enumerate(payload["rules"])
    )
    if not rules:
        raise BundleError(f"{path.name}: bundle declares no rules")

    return RuleBundle(
        bundle_id=str(payload["bundle_id"]),
        version=str(payload["version"]),
        published=bool(payload["published"]),
        content_sha256=_digest({"version": payload["version"], "rules": list(rules)}),
        document_types=tuple(payload.get("document_types") or ("guarantee",)),
        rules=rules,
        owner=payload.get("owner"),
        valid_from=payload.get("valid_from"),
        valid_to=payload.get("valid_to"),
        source=payload.get("source") or path.name,
    )


def load_bundles(
    directory: str | Path | None = None,
    *,
    document_type: str | None = None,
    include_unpublished: bool = False,
) -> list[RuleBundle]:
    """Load bundles for a document type. Unpublished bundles are skipped, not evaluated."""
    root = Path(directory) if directory is not None else BUNDLE_DIR
    bundles: list[RuleBundle] = []
    for path in sorted(root.glob("*.yaml")):
        bundle = load_bundle(path)
        if not include_unpublished and not bundle.published:
            continue
        if document_type is not None and document_type not in bundle.document_types:
            continue
        bundles.append(bundle)
    return bundles


def find_conflicts(bundles: list[RuleBundle]) -> list[str]:
    """Report published rules that contradict each other.

    Two checks, both deliberately conservative — we never silently prefer one source:

    1. the same `rule_id` published at two different versions;
    2. the same `(field_id, category)` with **different `gate_type`** coming from *different* bundles
       (one source says "hard block", another says "advisory" — the gate cannot honour both).
    """
    seen: dict[str, tuple[str, str]] = {}
    conflicts: list[str] = []
    for bundle in bundles:
        for rule in bundle.rules:
            rule_id, version = rule["rule_id"], str(rule["version"])
            previous = seen.get(rule_id)
            if previous is None:
                seen[rule_id] = (version, bundle.bundle_id)
            elif previous[0] != version:
                conflicts.append(
                    f"{rule_id} appears as v{previous[0]} in {previous[1]} and v{version} in {bundle.bundle_id}"
                )

    # Two *sources* disagreeing about how a field is gated. A single bundle may legitimately carry both
    # a hard-block and an advisory rule for one field, so only cross-bundle disagreement counts.
    gating: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for bundle in bundles:
        for rule in bundle.rules:
            key = (str(rule.get("field_id")), str(rule.get("category") or "field"))
            gating.setdefault(key, []).append((str(rule.get("gate_type")), bundle.bundle_id))

    for (field_id, category), entries in gating.items():
        for gate_type, bundle_id in entries:
            rivals = [
                (other_type, other_bundle)
                for other_type, other_bundle in entries
                if other_type != gate_type and other_bundle != bundle_id
            ]
            if rivals:
                other_type, other_bundle = rivals[0]
                conflicts.append(
                    f"{field_id or '<document>'}/{category} is gated inconsistently: "
                    f"{gate_type} in {bundle_id} vs {other_type} in {other_bundle}"
                )
                break
    return conflicts


def bundle_versions(bundles: list[RuleBundle]) -> dict[str, str]:
    return {bundle.bundle_id: bundle.version for bundle in bundles}


# Which literal types a field type may be compared with. Anything outside this table is a rule authoring
# error, caught at load time instead of degrading every document to "unable to assess".
LITERAL_COMPATIBILITY = {
    "amount": {"decimal"},
    "integer": {"decimal"},
    "date": {"date"},
    "currency": {"string"},
    "country": {"string"},
    "string": {"string"},
}


def _walk(expression: dict | None):
    """Yield every node of an expression tree."""
    if not isinstance(expression, dict):
        return
    yield expression
    for arg in expression.get("args") or ():
        yield from _walk(arg)
    if "arg" in expression:
        yield from _walk(expression["arg"])


def validate_against_schema(bundle: RuleBundle, schema) -> None:
    """Reject rules that cannot be evaluated against this schema, at load time.

    Two classes of authoring error are caught here instead of at run time:
    1. a rule referencing a field the schema does not define (usually a typo);
    2. a `compare` whose field type and literal type can never be compared
       (`currency` vs a decimal literal, `date` vs a `datetime` literal, …).
    """
    for rule in bundle.rules:
        where = f"{bundle.bundle_id}/{rule['rule_id']}@{rule['version']}"
        for expression in (*_walk(rule["expression"]), *_walk(rule.get("applicability"))):
            field_id = expression.get("field_id")
            if field_id is not None and field_id not in schema.fields:
                raise BundleError(f"{where}: unknown field {field_id!r}")
            if expression.get("op") != "compare":
                continue
            for field_side, literal_side in (("left", "right"), ("right", "left")):
                operand, other = expression[field_side], expression[literal_side]
                if operand.get("kind") != "field" or other.get("kind") != "literal":
                    continue
                ftype = schema.fields[operand["field_id"]].value_type
                allowed = LITERAL_COMPATIBILITY[ftype]
                if other["value_type"] not in allowed:
                    raise BundleError(
                        f"{where}: field {operand['field_id']!r} ({ftype}) cannot be compared with a "
                        f"{other['value_type']} literal; allowed: {sorted(allowed)}"
                    )