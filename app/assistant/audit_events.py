"""Audit event names and redaction helpers for egress and retrieval layers (design D10)."""

from __future__ import annotations

import hashlib

EGRESS_ALLOWED = "egress_allowed"
EGRESS_BLOCKED = "egress_blocked"
WEB_SEARCH_FAILED = "web_search_failed"
WEB_EVIDENCE_DROPPED = "web_evidence_dropped"
MODEL_CALL = "model_call"


def query_digest(text: str | None) -> str | None:
    """Irreversible fingerprint of the outbound query; never the query itself."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "EGRESS_ALLOWED",
    "EGRESS_BLOCKED",
    "MODEL_CALL",
    "WEB_EVIDENCE_DROPPED",
    "WEB_SEARCH_FAILED",
    "query_digest",
]