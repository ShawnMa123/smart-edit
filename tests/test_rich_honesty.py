"""Tasks 4.1/4.2 — rich structure is presentation only: it can never move an audit verdict."""

from __future__ import annotations

from app.audit.runner import audit_state

VALUES = {
    "guarantee_number": "BG-2026-00417",
    "guarantee_amount": "500000.00",
    "currency": "USD",
    "applicant_name": "Alpha Tech Pte Ltd",
    "beneficiary_name": "Beta Construction Ltd",
    "issue_date": "2026-03-12",
    "expiry_date": "2027-03-12",
    "governing_rules": "URDG 758",
}
DOCUMENT = "\n".join(["DEMAND GUARANTEE", *(f"{k}: {v}" for k, v in VALUES.items())])

RICH_HEADING = {
    "type": "doc",
    "provenance": "heuristic",
    "content": [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "DEMAND GUARANTEE"}]},
        *(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"{key}: {value}", "marks": ["bold"]}],
            }
            for key, value in VALUES.items()
        ),
    ],
}


def _field(key: str, value: str, *, status: str = "extracted") -> dict:
    return {
        "key": key,
        "value": value,
        "status": status,
        "confirmed": False,
        "edited_by_user": False,
        "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": value, "form_label": None}
        if status == "extracted"
        else None,
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


def _state(*, status: str = "extracted", rich: dict | None = None) -> dict:
    document = {"file_id": "F-1", "full_text": DOCUMENT}
    if rich is not None:
        document["rich"] = rich
    return {
        "business_type": "guarantee",
        "docs": [document],
        "fields": {key: _field(key, value, status=status) for key, value in VALUES.items()},
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "op": "read"}],
    }


def test_a_rich_document_cannot_change_the_verdict():
    """4.1 Formatting lives in `rich`; the engine only ever sees `full_text`, so counts must match."""
    plain = audit_state(_state(), snapshot_digest="d-1")["report"]
    formatted = audit_state(_state(rich=RICH_HEADING), snapshot_digest="d-1")["report"]

    assert formatted["counts"] == plain["counts"]
    assert formatted["outcome"] == plain["outcome"]
    assert formatted["coverage"] == plain["coverage"]
    assert formatted["findings"] == plain["findings"]


def test_formatting_an_ocr_value_does_not_confirm_it():
    """4.2 An OCR-derived value stays unconfirmed; bold text is not evidence."""
    plain = audit_state(_state(status="inferred"), snapshot_digest="d-1")["report"]
    formatted = audit_state(
        _state(status="inferred", rich=RICH_HEADING), snapshot_digest="d-1"
    )["report"]

    assert formatted["counts"] == plain["counts"]
    assert formatted["outcome"] == "needs_input", "unconfirmed values must still need a human"
    assert formatted["counts"]["pass"] == plain["counts"]["pass"]