"""Task 1.2 — `FieldValue` → audit value (design D7)."""

from __future__ import annotations

from app.audit.bind import ABSENT, CONFIRMED, UNCONFIRMED, VIOLATION, bind_field, bind_fields


def _field(**over):
    base = {
        "key": "guarantee_amount",
        "value": "500000.00",
        "status": "extracted",
        "confirmed": False,
        "edited_by_user": False,
        "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": "USD 500,000.00", "form_label": None},
        "normalized_from": "USD 500,000.00",
        "label": "保函金额",
        "doc_type": None,
        "notes": [],
    }
    return {**base, **over}


def test_absent_and_unconfirmed_and_confirmed_and_violation():
    assert bind_field("guarantee_amount", _field(value=None, status="missing")).state == ABSENT
    assert bind_field("guarantee_amount", None).state == ABSENT
    assert bind_field("guarantee_amount", _field(status="inferred")).state == UNCONFIRMED
    assert bind_field("guarantee_amount", _field()).state == CONFIRMED
    assert bind_field("guarantee_amount", _field(source=None)).state == VIOLATION


def test_extracted_counts_as_confirmed_even_before_hitl():
    # Design D7: `extracted` is locatable in its own file, so it may skip human confirmation.
    bound = bind_field("guarantee_amount", _field(confirmed=False, status="extracted"))
    assert bound.state == CONFIRMED
    assert bound.is_known is True


def test_unknown_status_is_a_violation_not_a_pass():
    assert bind_field("x", _field(status="bogus")).state == VIOLATION


def test_notes_and_source_survive_binding():
    bound = bind_field("x", _field(notes=["value_truncated"]))
    assert bound.notes == ("value_truncated",)
    assert bound.source["file_id"] == "F-1"


def test_bind_fields_covers_every_key():
    bound = bind_fields({"a": _field(), "b": None})
    assert set(bound) == {"a", "b"}
    assert bound["a"].state == CONFIRMED
    assert bound["b"].state == ABSENT


def test_bind_fields_tolerates_missing_mapping():
    assert bind_fields(None) == {}