"""What the audit judges, reduced to a digest (tasks 3.3 / 9.3).

A report must be able to say **which** snapshot it audited, and the gate must be able to tell "this
report is about the candidate you are submitting" from "this report is about yesterday's edit". Both
need one canonical digest of the candidate content — never of the derived findings, which would make
the digest depend on the audit itself.
"""

from __future__ import annotations

import hashlib
import json

# What counts as the candidate: the source files and the normalized values. A finding, a stage report
# or a trail entry is derived, so changing one must not change the digest.
_FIELD_KEYS = ("value", "status", "confirmed", "edited_by_user", "normalized_from", "source")


def candidate_payload(state: dict) -> dict:
    """The auditable content of a run, in a stable shape."""
    files = sorted(
        (
            {"file_id": item.get("file_id"), "sha256": item.get("sha256")}
            for item in state.get("files") or []
        ),
        key=lambda item: (str(item["file_id"]), str(item["sha256"])),
    )
    return {
        "files": files,
        "fields": _values(state.get("fields")),
        "extra_fields": _values(state.get("extra_fields")),
    }


def _values(fields: dict | None) -> dict:
    return {
        key: {name: (value or {}).get(name) for name in _FIELD_KEYS}
        for key, value in sorted((fields or {}).items())
    }


def snapshot_digest(state: dict) -> str:
    """SHA-256 over the canonical payload. Same content ⇒ same digest, on any machine."""
    canonical = json.dumps(
        candidate_payload(state), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()