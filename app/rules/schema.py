"""Project `app/configs/fields.yaml` into an audit schema bundle.

Design D4: the field dictionary is the schema source, and the bundle records a version hash so a report
can say which schema it was judged against. Character sets are resolved through an **approved
catalogue** — user-supplied regular expressions are not accepted (AI-audit §5.2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.config import load_fields_config

VALUE_TYPES = ("amount", "currency", "date", "integer", "string", "country")

# Approved character-set catalogue, keyed by the string used in fields.yaml.
CHARSET_CATALOGUE = {
    "0-9.": "digits_dot",
    "A-Z": "upper_alpha",
    "A-Z0-9-/": "alnum_dash_slash",
}
CATALOGUE_ALLOWED = {
    "digits_dot": "0123456789.",
    "upper_alpha": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "alnum_dash_slash": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/",
}


class SchemaError(ValueError):
    """The field dictionary cannot be used as an audit schema."""


@dataclass(frozen=True)
class FieldSchema:
    field_id: str
    value_type: str
    required: bool
    max_length: int | None = None
    charset_id: str | None = None
    precision: int | None = None
    date_order: str | None = None


@dataclass(frozen=True)
class SchemaBundle:
    version: str
    fields: dict[str, FieldSchema]


def _charset_id(field_id: str, raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        return CHARSET_CATALOGUE[raw]
    except KeyError:
        raise SchemaError(
            f"field {field_id!r} declares charset {raw!r}, which is not in the approved catalogue "
            f"({sorted(CHARSET_CATALOGUE)})"
        ) from None


def _version(payload: list[dict]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def build_schema(fields: dict[str, dict]) -> SchemaBundle:
    """Build a schema bundle from already-loaded field definitions."""
    if not fields:
        raise SchemaError("field dictionary is empty; refusing to audit against nothing")

    projected: dict[str, FieldSchema] = {}
    for key, fdef in fields.items():
        vtype = fdef.get("type")
        if vtype not in VALUE_TYPES:
            raise SchemaError(f"field {key!r} has unsupported type {vtype!r}")
        max_length = fdef.get("max_length")
        projected[key] = FieldSchema(
            field_id=key,
            value_type=vtype,
            required=bool(fdef.get("required", False)),
            max_length=int(max_length) if max_length is not None else None,
            charset_id=_charset_id(key, fdef.get("charset")),
            precision=int(fdef["precision"]) if fdef.get("precision") is not None else None,
            date_order=fdef.get("date_order"),
        )

    fingerprint = [
        {
            "field_id": f.field_id,
            "value_type": f.value_type,
            "required": f.required,
            "max_length": f.max_length,
            "charset_id": f.charset_id,
            "precision": f.precision,
            "date_order": f.date_order,
        }
        for f in projected.values()
    ]
    return SchemaBundle(version=_version(fingerprint), fields=projected)


def load_schema() -> SchemaBundle:
    """Load the repo's field dictionary as a schema bundle.

    A broken dictionary raises `FieldsConfigError` (from `app.config`) rather than yielding an empty
    schema — an empty schema would make every rule `not_applicable` and look like a clean audit.
    """
    return build_schema(load_fields_config())