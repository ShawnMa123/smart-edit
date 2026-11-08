"""Config loading and startup validation (`fields.yaml`).

Sources: `openspec/changes/agent-normalize/design.md` §7.7 / §9 last row,
`tasks.md` 1.1-1.7.

**Why validate at startup instead of falling back at runtime**:
`fields_yaml.get("fields", {})` returns `{}` when the file is missing, so every field silently
lands in `extra_fields`, `fields` is empty, and everything downstream is `missing` — a config
incident disguised as "the material did not say it". `load_fields_config()` therefore prefers to
raise, and **never** returns an empty dict.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# Field types: decides which value-normalization rule applies (design §7.3)
FIELD_TYPES = ("amount", "currency", "date", "integer", "string", "country")
# Only these constraints belong to `stage.normalize` (executed by A, design §7.7)
NORMALIZE_CONSTRAINTS = ("precision", "thousands", "max_length", "charset", "date_order")
# These belong to `stage.validate` (executed by B). A may only **read** `required`,
# and must never derive a blocking decision from it.
VALIDATE_CONSTRAINTS = ("required", "positive", "range", "enum")

DEFAULT_FIELDS_PATH = Path(__file__).resolve().parent / "configs" / "fields.yaml"


class FieldsConfigError(RuntimeError):
    """`fields.yaml` is missing / unparseable / structurally invalid.

    Raising this means "the whole run is fail": the caller must write three
    `StageReport(status="failed")` entries and **must not** continue with an empty dict.
    """


def resolve_fields_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("SMART_EDIT_FIELDS_YAML")
    if env:
        return Path(env)
    return DEFAULT_FIELDS_PATH


def load_fields_config(path: str | Path | None = None) -> dict[str, dict]:
    """Read `fields.yaml`, validate it, and return `{key: field_def}`.

    Anything invalid raises `FieldsConfigError` — an empty dict is never a legitimate load result.
    """
    target = resolve_fields_path(path)
    if not target.is_file():
        raise FieldsConfigError(f"fields.yaml missing or unreadable: {target}")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - triggered by invalid YAML
        raise FieldsConfigError(f"failed to parse fields.yaml: {target}: {exc}") from exc
    if raw is None:
        raise FieldsConfigError(f"fields.yaml is empty: {target}")
    return validate_fields_config(raw)


def validate_fields_config(raw: object) -> dict[str, dict]:
    """Pure validation function (no filesystem access), reusable by unit tests and startup."""
    if not isinstance(raw, dict) or "fields" not in raw:
        raise FieldsConfigError("fields.yaml must be a mapping with a top-level `fields` key")
    items = raw["fields"]
    if not isinstance(items, list) or not items:
        raise FieldsConfigError("`fields` must be a non-empty list")

    out: dict[str, dict] = {}
    for index, item in enumerate(items):
        where = f"fields[{index}]"
        if not isinstance(item, dict):
            raise FieldsConfigError(f"{where} must be a mapping")
        key = item.get("key")
        if not isinstance(key, str) or not key:
            raise FieldsConfigError(f"{where}.key is missing or not a string")
        where = f"field {key!r}"
        if key in out:
            raise FieldsConfigError(f"{where} is defined twice")

        for required_field in ("label", "aliases", "type", "required", "stage"):
            if required_field not in item:
                raise FieldsConfigError(f"{where} is missing {required_field}")

        ftype = item["type"]
        if ftype not in FIELD_TYPES:
            raise FieldsConfigError(f"{where}.type={ftype!r} is not one of {FIELD_TYPES}")

        # 1.5: `required` must be an explicit true / false, never defaulted to a falsy value
        if not isinstance(item["required"], bool):
            raise FieldsConfigError(f"{where}.required must be an explicit true/false")

        # 1.4: date fields must declare date_order explicitly (DMY / MDY / null)
        if "date_order" not in item:
            raise FieldsConfigError(f"{where} does not declare date_order explicitly (DMY/MDY/null)")
        if ftype == "date" and item["date_order"] not in ("DMY", "MDY", None):
            raise FieldsConfigError(f"{where}.date_order may only be DMY/MDY/null")
        if ftype != "date" and item["date_order"] is not None:
            raise FieldsConfigError(f"{where} is not a date field, date_order must be null")

        stage = item["stage"]
        if not isinstance(stage, dict):
            raise FieldsConfigError(f"{where}.stage must be a mapping")
        _check_stage(where, "normalize", stage, NORMALIZE_CONSTRAINTS)
        _check_stage(where, "validate", stage, VALIDATE_CONSTRAINTS)

        # 1.2 / 1.6: `required` belongs to validate only; A reads it and never blocks on it
        if "required" in stage["normalize"]:
            raise FieldsConfigError(
                f"{where}: required must not belong to stage.normalize (only B decides blocking)"
            )

        # 1.3: a constraint declared in stage.normalize must actually have a value on the field
        for constraint in stage["normalize"]:
            if constraint == "date_order":
                # `null` is a legitimate value for date fields ("keep the raw value, mark
                # date_ambiguous"); existence is already enforced by the explicit check above.
                continue
            if item.get(constraint) is None:
                raise FieldsConfigError(
                    f"{where}: stage.normalize declares {constraint} but the field has no value for it"
                )
        out[key] = item
    return out


def _check_stage(where: str, name: str, stage: dict, allowed: tuple[str, ...]) -> None:
    declared = stage.get(name)
    if not isinstance(declared, list):
        raise FieldsConfigError(f"{where}.stage.{name} must be a list")
    unknown = [c for c in declared if c not in allowed]
    if unknown:
        raise FieldsConfigError(
            f"{where}.stage.{name} contains unregistered constraints {unknown}, allowed: {allowed}"
        )