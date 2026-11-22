"""OpenAPI 3.x (JSON) → request-body contract, server side.

The browser already parses specs for its local preview (`web/src/automation/openapi.ts`); this module
is the same small subset in Python so the **real** dispatch builds the body from the downstream's own
schema instead of sending a flat bag of values:

* JSON only, `$ref` limited to `#/...`, object schemas flattened into dotted scalar paths;
* unsupported constructs (`oneOf`/`anyOf`, arrays, external refs, cycles) are reported, never guessed;
* nothing is coerced silently: a value that does not fit the schema is an issue, not a string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_SPEC_BYTES = 512 * 1024
SCALAR_TYPES = ("string", "number", "integer", "boolean")
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class SpecError(ValueError):
    """The document is not a usable OpenAPI 3.x JSON spec."""


@dataclass
class SpecField:
    path: str
    type: str
    required: bool = False
    enum: list[str] = field(default_factory=list)
    description: str | None = None
    unsupported: str | None = None


@dataclass
class SpecOperation:
    id: str
    method: str
    path: str
    operation_id: str | None = None
    summary: str | None = None
    content_type: str | None = None
    fields: list[SpecField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.content_type) and any(
            item.unsupported is None and item.type in SCALAR_TYPES for item in self.fields
        )


@dataclass
class OpenApiSpec:
    title: str
    version: str
    operations: list[SpecOperation] = field(default_factory=list)

    def operation(self, operation_id: str | None) -> SpecOperation | None:
        if not operation_id:
            return None
        return next((item for item in self.operations if item.id == operation_id), None)

    def default_operation(self) -> SpecOperation | None:
        """First usable write operation, so `POST` wins over `GET` and unusable paths are skipped."""
        preferred = ("POST", "PUT", "PATCH", "DELETE")
        usable = [item for item in self.operations if item.available]
        for method in preferred:
            match = next((item for item in usable if item.method == method), None)
            if match is not None:
                return match
        return usable[0] if usable else None


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _resolve_pointer(root: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    current: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not _is_record(current) or token not in current:
            return None
        current = current[token]
    return current


def _deref(value: Any, root: dict[str, Any], label: str, warnings: set[str]) -> dict[str, Any] | None:
    current = value
    seen: set[str] = set()
    while _is_record(current) and isinstance(current.get("$ref"), str):
        ref = current["$ref"]
        if not ref.startswith("#/"):
            warnings.add(f"{label}: external $ref {ref} is not supported")
            return None
        if ref in seen:
            warnings.add(f"{label}: circular $ref {ref}")
            return None
        seen.add(ref)
        current = _resolve_pointer(root, ref)
        if not _is_record(current):
            warnings.add(f"{label}: unresolved $ref {ref}")
            return None
    return current if _is_record(current) else None


def _collect(
    schema: Any,
    prefix: str,
    root: dict[str, Any],
    fields: list[SpecField],
    warnings: set[str],
    visiting: set[int],
    required: bool,
) -> None:
    resolved = _deref(schema, root, prefix or "request schema", warnings)
    if resolved is None:
        return

    identity = id(resolved)
    if identity in visiting:
        warnings.add(f"{prefix or 'request schema'}: circular schema reference")
        if prefix:
            fields.append(SpecField(prefix, "unknown", required, unsupported="circular schema"))
        return

    visiting.add(identity)
    try:
        if "oneOf" in resolved or "anyOf" in resolved:
            warnings.add(f"{prefix or 'request schema'}: oneOf/anyOf is not supported")
            if prefix:
                fields.append(
                    SpecField(prefix, "unknown", required, unsupported="oneOf/anyOf is not supported")
                )
            return

        declared = resolved.get("type")
        if declared == "object" or (declared is None and "properties" in resolved):
            properties = resolved.get("properties")
            if not _is_record(properties) or not properties:
                if prefix:
                    fields.append(
                        SpecField(prefix, "object", required, unsupported="object without properties")
                    )
                return
            child_required = set(resolved.get("required") or [])
            for name, child in properties.items():
                path = f"{prefix}.{name}" if prefix else str(name)
                _collect(child, path, root, fields, warnings, visiting, str(name) in child_required)
            return

        if declared == "array":
            warnings.add(f"{prefix or 'request schema'}: array fields are not supported")
            if prefix:
                fields.append(SpecField(prefix, "array", required, unsupported="array"))
            return

        if declared not in SCALAR_TYPES:
            warnings.add(f"{prefix or 'request schema'}: missing or unsupported type")
            if prefix:
                fields.append(
                    SpecField(prefix, "unknown", required, unsupported="missing or unsupported type")
                )
            return

        if not prefix:  # a bare scalar body cannot be mapped from named variables
            warnings.add("request schema: top-level scalar body is not supported")
            return

        enum_values = [str(item) for item in resolved.get("enum") or []]
        description = resolved.get("description")
        fields.append(
            SpecField(
                path=prefix,
                type=str(declared),
                required=required,
                enum=enum_values,
                description=str(description) if isinstance(description, str) else None,
            )
        )
    finally:
        visiting.discard(identity)


def parse_spec(document: Any) -> OpenApiSpec:
    """Validate and flatten an OpenAPI 3.x JSON document. Raises `SpecError` when unusable."""
    if not _is_record(document):
        raise SpecError("The document must be a JSON object.")
    if document.get("swagger") is not None:
        raise SpecError("Swagger 2.0 is not supported. Provide an OpenAPI 3.x JSON document.")
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise SpecError("Only OpenAPI 3.x JSON is supported.")
    paths = document.get("paths")
    if not _is_record(paths) or not paths:
        raise SpecError("The OpenAPI document has no paths object.")

    info = document.get("info")
    title = str(info["title"]) if _is_record(info) and info.get("title") else "Untitled API"
    api_version = str(info["version"]) if _is_record(info) and info.get("version") else "unknown"

    operations: list[SpecOperation] = []
    for path, path_item in paths.items():
        if not _is_record(path_item):
            continue
        for method in METHODS:
            operation = path_item.get(method)
            if not _is_record(operation):
                continue
            label = f"{method.upper()} {path}"
            warnings: set[str] = set()
            fields: list[SpecField] = []
            content_type: str | None = None

            request_body = _deref(operation.get("requestBody"), document, label, warnings)
            schema: Any = None
            if request_body is None:
                warnings.add("No request body.")
            else:
                content = request_body.get("content")
                if _is_record(content):
                    for media, media_object in content.items():
                        if str(media).split(";")[0].strip().lower() != "application/json":
                            continue
                        if _is_record(media_object) and media_object.get("schema") is not None:
                            content_type = str(media)
                            schema = media_object["schema"]
                        break
                if schema is None:
                    warnings.add("No application/json request body.")

            if schema is not None:
                _collect(schema, "", document, fields, warnings, set(), True)

            operations.append(
                SpecOperation(
                    id=label,
                    method=method.upper(),
                    path=str(path),
                    operation_id=(
                        str(operation["operationId"])
                        if isinstance(operation.get("operationId"), str)
                        else None
                    ),
                    summary=(
                        str(operation["summary"])
                        if isinstance(operation.get("summary"), str)
                        else None
                    ),
                    content_type=content_type,
                    fields=fields,
                    warnings=sorted(warnings),
                )
            )

    if not operations:
        raise SpecError("The OpenAPI document has no operations.")
    return OpenApiSpec(title=title, version=api_version, operations=operations)


def _normalize(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


# A leaf called `name`/`date`/... says little; its parent segment is the meaningful noun
# (`beneficiary.name` → the `Beneficiary` variable).
GENERIC_LEAVES = frozenset(
    ("name", "no", "number", "ref", "reference", "code", "id", "value", "text", "amount", "date")
)


def suggest_mapping(operation: SpecOperation, labels: Iterable[tuple[str, str]]) -> dict[str, str]:
    """`{field path: variable key}`, most specific match first, generic leaves falling back to parent."""
    by_label = {_normalize(label): key for key, label in labels if label}
    mapping: dict[str, str] = {}
    for item in operation.fields:
        if item.unsupported:
            continue
        segments = item.path.split(".")
        match = by_label.get(_normalize(segments[-1])) or by_label.get(_normalize(item.path))
        if not match and segments[-1].lower() in GENERIC_LEAVES:
            for parent in reversed(segments[:-1]):
                match = by_label.get(_normalize(parent))
                if match:
                    break
        if match:
            mapping[item.path] = match
    return mapping


def _numeric(value: str) -> float | None:
    """Numeric fields accept what documents actually contain: `USD 750,000.00`, `1 200,5`, `60 days`."""
    cleaned = value.replace(",", "").replace("，", "").replace("\u00a0", " ")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


def _convert(value: str, field_type: str) -> tuple[bool, Any]:
    if field_type == "string":
        return True, value
    if field_type == "number":
        number = _numeric(value)
        return (True, number) if number is not None else (False, None)
    if field_type == "integer":
        number = _numeric(value)
        if number is None:
            return False, None
        return (True, int(number)) if number.is_integer() else (False, None)
    if field_type == "boolean":
        lowered = value.strip().lower()
        if lowered in ("true", "false"):
            return True, lowered == "true"
        return False, None
    return False, None


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        node = current.get(part)
        if not isinstance(node, dict):
            node = {}
            current[part] = node
        current = node
    current[parts[-1]] = value


@dataclass
class BodyBuild:
    body: dict[str, Any]
    mapping: dict[str, str]
    issues: list[dict[str, str]]
    missing: list[str]
    invalid: list[str]

    @property
    def ready(self) -> bool:
        return not self.issues


def build_body(
    operation: SpecOperation,
    mapping: dict[str, str],
    values: dict[str, str | None],
) -> BodyBuild:
    """Assemble the request body the spec asks for. Unmapped optional fields are simply omitted."""
    body: dict[str, Any] = {}
    issues: list[dict[str, str]] = []
    missing: list[str] = []
    invalid: list[str] = []

    for item in operation.fields:
        if item.unsupported:
            if item.required:
                issues.append(
                    {
                        "path": item.path,
                        "reason": "unsupported",
                        "message": f"Required field uses an unsupported schema ({item.unsupported}).",
                    }
                )
                missing.append(item.path)
            continue

        key = mapping.get(item.path)
        if not key:
            if item.required:
                issues.append(
                    {
                        "path": item.path,
                        "reason": "missing",
                        "message": "Required field has no mapped variable.",
                    }
                )
                missing.append(item.path)
            continue

        raw = values.get(key)
        value = (raw or "").strip()
        if not value:
            if item.required:
                issues.append(
                    {
                        "path": item.path,
                        "reason": "missing",
                        "message": f"Required field is empty (variable `{key}`).",
                    }
                )
                missing.append(item.path)
            continue

        if item.enum and value not in item.enum:
            issues.append(
                {
                    "path": item.path,
                    "reason": "invalid",
                    "message": f"Value must be one of: {', '.join(item.enum)}.",
                }
            )
            invalid.append(item.path)
            continue

        ok, converted = _convert(value, item.type)
        if not ok:
            issues.append(
                {
                    "path": item.path,
                    "reason": "invalid",
                    "message": f"Value cannot be converted to {item.type}.",
                }
            )
            invalid.append(item.path)
            continue

        _set_path(body, item.path, converted)

    return BodyBuild(
        body=body,
        mapping=dict(mapping),
        issues=issues,
        missing=missing,
        invalid=invalid,
    )


def operation_from_fields(
    fields: Iterable[dict[str, Any]], *, method: str, path: str
) -> SpecOperation:
    """Synthesize the same `SpecOperation` shape from hand-written fields.

    Keeps one code path for mapping, validation and body assembly: a connector without an OpenAPI
    document behaves exactly like one with a one-operation document.
    """
    items: list[SpecField] = []
    for raw in fields:
        field_path = str(raw.get("path") or "").strip()
        if not field_path:
            continue
        field_type = str(raw.get("type") or "string").lower()
        if field_type not in SCALAR_TYPES:
            field_type = "string"
        items.append(
            SpecField(
                path=field_path,
                type=field_type,
                required=bool(raw.get("required")),
            )
        )
    return SpecOperation(
        id=f"CUSTOM {path}",
        method=method.upper(),
        path=path,
        operation_id="custom-fields",
        summary="Hand-written request fields",
        content_type="application/json",
        fields=items,
        warnings=[],
    )


__all__ = [
    "BodyBuild",
    "MAX_SPEC_BYTES",
    "OpenApiSpec",
    "SpecError",
    "SpecField",
    "SpecOperation",
    "build_body",
    "operation_from_fields",
    "parse_spec",
    "suggest_mapping",
]