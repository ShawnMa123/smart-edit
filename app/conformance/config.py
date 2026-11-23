"""Calibration configs for the template-conformance audit.

A config is data, not code: no regex, no script, no prompt text. It carries two layers:

- `fields.required` — the deterministic layer decides these from `fields.yaml` and an extraction
  profile; the model never decides that a required field is missing.
- `requirements[]` — the model judges these one by one and must quote the document for every
  finding.

Every config is versioned and fingerprinted so a report can name exactly what it was judged against.
Unknown / unpublished / malformed configs are refused, never silently replaced by another one.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LEVELS = ("must", "should", "info")
ENV_DIR = "SMART_EDIT_CONFORMANCE_DIR"
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "configs" / "conformance"


class ConfigError(ValueError):
    """A calibration config is missing, unparseable or structurally invalid."""


@dataclass(frozen=True)
class Requirement:
    """One expectation the model has to judge, with the desk wording kept verbatim."""

    id: str
    title: str
    level: str
    check: str | None = None
    evidence_hint: str | None = None
    suggestion: str | None = None

    def prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "title": self.title, "level": self.level}
        if self.check:
            payload["check"] = self.check
        if self.evidence_hint:
            payload["evidence_hint"] = self.evidence_hint
        return payload


@dataclass(frozen=True)
class Generation:
    """Limits the server enforces after the model answers; the model cannot widen them."""

    max_findings: int = 12
    max_quote_chars: int = 300
    summary_max_chars: int = 600
    max_document_chars: int = 24000
    # Long documents are judged chunk by chunk (finding wins over pass when merged). A chunk never
    # exceeds this; the total sent never exceeds `max_document_chars`.
    chunk_chars: int = 6000


@dataclass(frozen=True)
class ConformanceConfig:
    config_id: str
    version: str
    published: bool
    name: str
    document_types: tuple[str, ...] = ("guarantee",)
    language: str = "auto"
    description: str = ""
    extraction_profile: str | None = None
    required_fields: tuple[str, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    generation: Generation = field(default_factory=Generation)
    content_sha256: str = ""

    def requirement(self, requirement_id: str) -> Requirement | None:
        return next((item for item in self.requirements if item.id == requirement_id), None)

    @property
    def requirement_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.requirements)


def resolve_dir(directory: str | Path | None = None) -> Path:
    """Config directory: explicit argument > env override > packaged default."""
    if directory is not None:
        return Path(directory)
    override = (os.environ.get(ENV_DIR) or "").strip()
    return Path(override) if override else DEFAULT_DIR


def _text(raw: Any, where: str, *, required: bool = True, limit: int = 2000) -> str | None:
    if raw is None:
        if required:
            raise ConfigError(f"{where} is required")
        return None
    value = str(raw).strip()
    if not value:
        if required:
            raise ConfigError(f"{where} must not be empty")
        return None
    return value[:limit]


def _positive_int(raw: Any, where: str, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{where} must be an integer") from None
    if value <= 0:
        raise ConfigError(f"{where} must be greater than zero")
    return value


def _requirement(raw: Any, where: str) -> Requirement:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")
    requirement_id = _text(raw.get("id"), f"{where}.id", limit=80) or ""
    if " " in requirement_id:
        raise ConfigError(f"{where}.id must not contain spaces")
    level = _text(raw.get("level"), f"{where}.level", limit=20) or ""
    if level not in LEVELS:
        raise ConfigError(f"{where}.level must be one of {LEVELS}")
    return Requirement(
        id=requirement_id,
        title=_text(raw.get("title"), f"{where}.title", limit=200) or requirement_id,
        level=level,
        check=_text(raw.get("check"), f"{where}.check", required=False, limit=1000),
        evidence_hint=_text(
            raw.get("evidence_hint"), f"{where}.evidence_hint", required=False, limit=300
        ),
        suggestion=_text(raw.get("suggestion"), f"{where}.suggestion", required=False, limit=600),
    )


def _generation(raw: Any, where: str) -> Generation:
    if raw is None:
        return Generation()
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")
    generation = Generation(
        max_findings=_positive_int(raw.get("max_findings"), f"{where}.max_findings", 12),
        max_quote_chars=_positive_int(raw.get("max_quote_chars"), f"{where}.max_quote_chars", 300),
        summary_max_chars=_positive_int(
            raw.get("summary_max_chars"), f"{where}.summary_max_chars", 600
        ),
        max_document_chars=_positive_int(
            raw.get("max_document_chars"), f"{where}.max_document_chars", 24000
        ),
        chunk_chars=_positive_int(raw.get("chunk_chars"), f"{where}.chunk_chars", 6000),
    )
    if generation.max_document_chars < 1000:
        raise ConfigError(f"{where}.max_document_chars must be at least 1000")
    if generation.chunk_chars < 500:
        raise ConfigError(f"{where}.chunk_chars must be at least 500")
    if generation.chunk_chars > generation.max_document_chars:
        raise ConfigError(f"{where}.chunk_chars must not exceed max_document_chars")
    return generation


def validate_config(payload: Any, *, where: str = "config") -> ConformanceConfig:
    """Validate one config mapping; every failure names the offending key."""
    if not isinstance(payload, dict):
        raise ConfigError(f"{where}: config must be a mapping")

    config_id = _text(payload.get("config_id"), f"{where}.config_id", limit=80) or ""
    if "/" in config_id or ".." in config_id:
        raise ConfigError(f"{where}.config_id must be a plain identifier")
    version = _text(payload.get("version"), f"{where}.version", limit=40) or ""
    published = payload.get("published")
    if not isinstance(published, bool):
        raise ConfigError(f"{where}.published must be an explicit true/false")

    document_types = payload.get("document_types") or ["guarantee"]
    if not isinstance(document_types, list) or not all(
        isinstance(item, str) and item.strip() for item in document_types
    ):
        raise ConfigError(f"{where}.document_types must be a list of non-empty strings")

    fields_raw = payload.get("fields") or {}
    if not isinstance(fields_raw, dict):
        raise ConfigError(f"{where}.fields must be a mapping")
    required_fields = fields_raw.get("required") or []
    if not isinstance(required_fields, list) or not all(
        isinstance(item, str) and item.strip() for item in required_fields
    ):
        raise ConfigError(f"{where}.fields.required must be a list of field keys")
    if len(set(required_fields)) != len(required_fields):
        raise ConfigError(f"{where}.fields.required contains a duplicate key")

    requirements_raw = payload.get("requirements") or []
    if not isinstance(requirements_raw, list):
        raise ConfigError(f"{where}.requirements must be a list")
    requirements = tuple(
        _requirement(item, f"{where}.requirements[{index}]")
        for index, item in enumerate(requirements_raw)
    )
    ids = [item.id for item in requirements]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"{where}.requirements contains a duplicate id")
    if not required_fields and not requirements:
        raise ConfigError(f"{where}: config declares no requirement at all")

    generation = _generation(payload.get("generation"), f"{where}.generation")
    description = _text(payload.get("description"), f"{where}.description", required=False) or ""

    fingerprint = {
        "config_id": config_id,
        "version": version,
        "published": published,
        "name": payload.get("name"),
        "document_types": list(document_types),
        "language": payload.get("language") or "auto",
        "description": description,
        "extraction_profile": payload.get("extraction_profile"),
        "required_fields": list(required_fields),
        "requirements": [vars(item) for item in requirements],
        "generation": vars(generation),
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return ConformanceConfig(
        config_id=config_id,
        version=version,
        published=published,
        name=_text(payload.get("name"), f"{where}.name", limit=160) or config_id,
        document_types=tuple(str(item).strip() for item in document_types),
        language=str(payload.get("language") or "auto").strip() or "auto",
        description=description,
        extraction_profile=(
            _text(payload.get("extraction_profile"), f"{where}.extraction_profile", required=False)
        ),
        required_fields=tuple(str(item).strip() for item in required_fields),
        requirements=requirements,
        generation=generation,
        content_sha256=digest,
    )


def load_config(path: str | Path) -> ConformanceConfig:
    target = Path(path)
    if not target.is_file():
        raise ConfigError(f"conformance config missing or unreadable: {target}")
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"failed to parse conformance config {target}: {exc}") from exc
    config = validate_config(payload, where=target.name)
    if config.config_id != target.stem:
        raise ConfigError(
            f"{target.name} declares config_id {config.config_id!r}; the file name must match"
        )
    return config


def load_configs(directory: str | Path | None = None) -> list[ConformanceConfig]:
    """Every published config in the directory, sorted by id."""
    root = resolve_dir(directory)
    if not root.exists():
        return []
    configs = [load_config(path) for path in sorted(root.glob("*.yaml"))]
    return [config for config in configs if config.published]


def get_config(config_id: str, directory: str | Path | None = None) -> ConformanceConfig:
    """Resolve one published config by id; unknown ids raise instead of falling back."""
    clean = (config_id or "").strip()
    if not clean:
        raise ConfigError("config_id must be a non-empty string")
    for config in load_configs(directory):
        if config.config_id == clean:
            return config
    raise ConfigError(f"conformance config {clean!r} is unknown or not published")


__all__ = [
    "ConfigError",
    "ConformanceConfig",
    "DEFAULT_DIR",
    "ENV_DIR",
    "Generation",
    "LEVELS",
    "Requirement",
    "get_config",
    "load_config",
    "load_configs",
    "resolve_dir",
    "validate_config",
]