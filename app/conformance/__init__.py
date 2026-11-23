"""Template-conformance audit: calibration configs, redaction, Doubao composition and reports.

The audit reads one server draft (pinned by revision + sha), checks required fields
deterministically, then asks the approved Doubao model to judge the config requirements against the
document text. Every model finding must quote the document; the server validates the quote and caps
severity, so the model can never invent a defect or escalate a gate.
"""

from __future__ import annotations

__all__ = ["config", "contracts", "compose", "redact", "service", "store"]