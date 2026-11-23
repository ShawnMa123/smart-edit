"""Versioned extraction profiles: *where* a value is found, never *what* a field means.

Sources: `openspec/changes/config-driven-audit-extraction/design.md` D1/D2/D7,
spec: `openspec/changes/config-driven-audit-extraction/specs/audit-extraction/spec.md`.

Three rules, all enforced at load time:

1. A profile only **references** `fields.yaml` keys; the dictionary stays the one source of field types.
2. Value shapes come from the closed `value_kind` set. There is no inline regular expression, script or
   command — an unknown key is a load error, not something to ignore.
3. Only published profiles whose `document_types` match may be used. Unknown / unpublished / mismatched
   profiles are refused, never silently replaced by the fixture path.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.config import FieldsConfigError, load_fields_config

VALUE_KINDS = ("amount", "date", "currency", "integer", "text", "clause_text")
SEARCH_MODES = ("same_block", "same_or_next_block")

# A profile field may only use a kind its `fields.yaml` type can normalize. The table is deliberately
# narrow: adding a kind means adding a tested tokenizer, never loosening the config schema.
KIND_FIELD_TYPES = {
    "amount": frozenset({"amount"}),
    "date": frozenset({"date"}),
    "currency": frozenset({"currency"}),
    "integer": frozenset({"integer"}),
    "text": frozenset({"string", "country"}),
    "clause_text": frozenset({"string"}),
}

_PROFILE_KEYS = {
    "profile_id",
    "version",
    "published",
    "document_types",
    "description",
    "fields",
    "llm_fallback",
}
_FIELD_KEYS = {"labels", "value_kind", "search", "max_chars", "confidence"}
_FALLBACK_KEYS = {"enabled"}

# Hard ceiling: a locator may not scan an unbounded fragment. 1000 chars is far above any field in
# `fields.yaml` and still keeps the tokenizers linear.
MAX_LOOKUP_CHARS = 1000

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parent.parent / "configs" / "extraction"


class ProfileError(ValueError):
    """An extraction profile is missing / unparseable / structurally invalid / not usable."""


@dataclass(frozen=True)
class ProfileField:
    key: str
    labels: tuple[str, ...]
    value_kind: str
    search: str
    max_chars: int
    confidence: float


@dataclass(frozen=True)
class ExtractionProfile:
    profile_id: str
    version: str
    published: bool
    document_types: tuple[str, ...]
    fields: dict[str, ProfileField]
    content_sha256: str
    llm_fallback: dict

    @property
    def identity(self) -> dict:
        """The block written into the audit report. No candidates, no values."""
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "content_sha256": self.content_sha256,
            "document_types": list(self.document_types),
        }


def resolve_profile_dir(directory: str | Path | None = None) -> Path:
    if directory is not None:
        return Path(directory)
    env = os.environ.get("SMART_EDIT_EXTRACTION_PROFILES")
    if env:
        return Path(env)
    return DEFAULT_PROFILE_DIR


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _reject_extra_keys(payload: dict, allowed: set[str], where: str) -> None:
    extra = sorted(set(payload) - allowed)
    if extra:
        # This is also what rejects `pattern` / `regex` / `script`: they are not part of the closed
        # schema, so they can never be smuggled into a locator.
        raise ProfileError(f"{where}: unsupported key(s) {extra}; allowed: {sorted(allowed)}")


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ProfileError(f"{where}: missing {key}")
    return mapping[key]


def _field(raw: object, where: str, fields_config: dict[str, dict]) -> ProfileField:
    if not isinstance(raw, dict):
        raise ProfileError(f"{where}: field rule must be a mapping")
    _reject_extra_keys(raw, _FIELD_KEYS, where)

    labels = _require(raw, "labels", where)
    if not isinstance(labels, list) or not labels:
        raise ProfileError(f"{where}.labels must be a non-empty list of label/alias strings")
    cleaned: list[str] = []
    for label in labels:
        if not isinstance(label, str) or not label.strip():
            raise ProfileError(f"{where}.labels entries must be non-empty strings")
        cleaned.append(label.strip())

    value_kind = _require(raw, "value_kind", where)
    if value_kind not in VALUE_KINDS:
        raise ProfileError(f"{where}.value_kind={value_kind!r} is not one of {VALUE_KINDS}")

    search = raw.get("search", "same_block")
    if search not in SEARCH_MODES:
        raise ProfileError(f"{where}.search={search!r} is not one of {SEARCH_MODES}")

    max_chars = raw.get("max_chars", 200)
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not (
        0 < max_chars <= MAX_LOOKUP_CHARS
    ):
        raise ProfileError(f"{where}.max_chars must be an integer in 1..{MAX_LOOKUP_CHARS}")

    confidence = raw.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ProfileError(f"{where}.confidence must be a number")
    if not 0 <= float(confidence) <= 1:
        raise ProfileError(f"{where}.confidence must be within 0..1")

    key = where.rsplit("/", 1)[-1]
    ftype = fields_config[key].get("type")
    allowed_types = KIND_FIELD_TYPES[value_kind]
    if ftype not in allowed_types:
        raise ProfileError(
            f"{where}: value_kind {value_kind!r} is not compatible with fields.yaml type {ftype!r}; "
            f"allowed types: {sorted(allowed_types)}"
        )

    return ProfileField(
        key=key,
        labels=tuple(cleaned),
        value_kind=value_kind,
        search=search,
        max_chars=max_chars,
        confidence=float(confidence),
    )


def validate_profile(raw: object, *, fields_config: dict[str, dict] | None = None) -> ExtractionProfile:
    """Pure validation (no filesystem access) so tests and startup share one rule set."""
    if not isinstance(raw, dict):
        raise ProfileError("profile must be a JSON object")
    _reject_extra_keys(raw, _PROFILE_KEYS, "profile")

    profile_id = _require(raw, "profile_id", "profile")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ProfileError("profile.profile_id must be a non-empty string")
    profile_id = profile_id.strip()

    version = _require(raw, "version", "profile")
    if not isinstance(version, str) or not version.strip():
        raise ProfileError("profile.version must be a non-empty string")
    version = version.strip()

    published = _require(raw, "published", "profile")
    if not isinstance(published, bool):
        raise ProfileError("profile.published must be an explicit true/false")

    document_types = _require(raw, "document_types", "profile")
    if not isinstance(document_types, list) or not document_types:
        raise ProfileError("profile.document_types must be a non-empty list")
    types = []
    for item in document_types:
        if not isinstance(item, str) or not item.strip():
            raise ProfileError("profile.document_types entries must be non-empty strings")
        types.append(item.strip())

    raw_fields = _require(raw, "fields", "profile")
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise ProfileError("profile.fields must be a non-empty mapping")


    if fields_config is None:
        try:
            fields_config = load_fields_config()
        except FieldsConfigError as exc:
            raise ProfileError(f"fields.yaml unavailable while validating profile: {exc}") from exc

    fields: dict[str, ProfileField] = {}
    for key, rule in raw_fields.items():
        if not isinstance(key, str) or not key:
            raise ProfileError("profile.fields keys must be non-empty strings")
        if key not in fields_config:
            raise ProfileError(
                f"profile/{key}: unknown field key; it is not declared in fields.yaml "
                f"({sorted(fields_config)})"
            )
        fields[key] = _field(rule, f"profile/{key}", fields_config)

    fallback_raw = raw.get("llm_fallback", {"enabled": False})
    if not isinstance(fallback_raw, dict):
        raise ProfileError("profile.llm_fallback must be a mapping")
    _reject_extra_keys(fallback_raw, _FALLBACK_KEYS, "profile.llm_fallback")
    enabled = fallback_raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProfileError("profile.llm_fallback.enabled must be an explicit true/false")

    fingerprint = {
        "profile_id": profile_id,
        "version": version,
        "published": published,
        "document_types": types,
        "fields": {
            key: {**vars(field), "labels": list(field.labels)} for key, field in fields.items()
        },
        "llm_fallback": {"enabled": enabled},
    }
    return ExtractionProfile(
        profile_id=profile_id,
        version=version,
        published=published,
        document_types=tuple(types),
        fields=fields,
        content_sha256=_digest(fingerprint),
        llm_fallback={"enabled": enabled},
    )


def load_profile(
    path: str | Path,
    *,
    fields_config: dict[str, dict] | None = None,
    document_type: str | None = None,
    require_published: bool = True,
) -> ExtractionProfile:
    """Load one profile file, then apply the publication/type gates."""
    target = Path(path)
    if not target.is_file():
        raise ProfileError(f"extraction profile missing or unreadable: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"failed to parse extraction profile {target}: {exc}") from exc

    profile = validate_profile(payload, fields_config=fields_config)

    if require_published and not profile.published:
        raise ProfileError(f"extraction profile {profile.profile_id!r} is not published")
    if document_type is not None and document_type not in profile.document_types:
        raise ProfileError(
            f"extraction profile {profile.profile_id!r} does not apply to document type "
            f"{document_type!r}; declared: {list(profile.document_types)}"
        )
    return profile


def load_profile_by_id(
    profile_id: str,
    *,
    directory: str | Path | None = None,
    fields_config: dict[str, dict] | None = None,
    document_type: str | None = None,
    require_published: bool = True,
) -> ExtractionProfile:
    """Resolve `profile_id` under the profile directory; every failure is readable."""
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ProfileError("profile id must be a non-empty string")
    root = resolve_profile_dir(directory)
    profile = load_profile(
        root / f"{profile_id}.json",
        fields_config=fields_config,
        document_type=document_type,
        require_published=require_published,
    )
    if profile.profile_id != profile_id:
        raise ProfileError(
            f"profile file {profile_id}.json declares profile_id {profile.profile_id!r}; "
            "refusing a mismatch"
        )
    return profile


def resolve_profile(
    *,
    requested: str | None = None,
    template=None,
    directory: str | Path | None = None,
    fields_config: dict[str, dict] | None = None,
    document_type: str | None = None,
) -> ExtractionProfile | None:
    """Resolution order (design D7): request `?profile=` > template > no profile.

    A request naming an unknown / unpublished / mismatched profile raises; it never falls back to the
    template or to the fixture path. A template's profile is loaded through the same gates.
    """
    if requested:
        return load_profile_by_id(
            requested,
            directory=directory,
            fields_config=fields_config,
            document_type=document_type,
        )
    declared = getattr(template, "extraction_profile", None) if template is not None else None
    if declared:
        return load_profile_by_id(
            declared,
            directory=directory,
            fields_config=fields_config,
            document_type=document_type,
        )
    return None

