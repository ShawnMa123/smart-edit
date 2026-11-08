"""The one place a response body is assembled.

Design: `openspec/changes/frontend-console/design.md` D4. The invariant that matters: a client must
never be told "clean" because `stages` was missing, so a state without `stages` raises
`IncompleteResult` (→ `500 INCOMPLETE_RESULT`) instead of serialising an empty list.
"""

from __future__ import annotations

from app.api.errors import IncompleteResult
from app.stages import STAGE_TARGETS


def supported_stages() -> list[str]:
    """What this build can execute, derived from the registry that gates execution (D8)."""
    return sorted(STAGE_TARGETS)


def to_envelope(state: dict) -> dict:
    """Serialise a run state for clients."""
    if "stages" not in state:
        raise IncompleteResult("run state has no `stages`; refusing to report a result")

    return {
        "thread_id": state.get("run_id"),
        "business_type": state.get("business_type"),
        "files": state.get("files") or [],
        "fields": state.get("fields") or {},
        "extra_fields": state.get("extra_fields") or {},
        "findings": state.get("findings") or [],
        "stages": state.get("stages") or [],
        "trail": state.get("trail") or [],
        "_candidates": state.get("_candidates") or [],
        # Import surface (`document-import` D7): what was read out of each uploaded file. `[]` means
        # "nothing parsed yet" — never a fabricated text, and `form` says read vs recognised.
        "documents": [
            {
                "file_id": doc.get("file_id"),
                "filename": doc.get("filename"),
                "form": doc.get("form"),
                "errors": doc.get("errors") or [],
                "full_text": doc.get("full_text") or "",
            }
            for doc in state.get("docs") or []
        ],
        # Audit surfaces (tasks 6.3): `null` means "no audit yet" / "the gate was never asked" — it
        # never means "clean", so a client must not read a missing value as approval.
        "verification": state.get("verification"),
        "gate": state.get("gate"),
        "supported_stages": supported_stages(),
    }