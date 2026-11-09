"""Executable assertions for seam A -> B (tasks 10.1 / 10.2 / 10.4).

**Assertions only, no golden files**: what downstream (Agent 2) emits depends on its own rules;
only these few properties are stable.

How to run (from the repo root):
    .venv/bin/python -m pytest fixtures/seam_a_to_b/assert.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import load_fields_config
from app.parsing.normalize import MAX_SPAN_LEN, normalize_ws

STATE = json.loads(Path(__file__).with_name("input.json").read_text(encoding="utf-8"))
FIELDS = STATE["fields"]
EXTRA = STATE["extra_fields"]
ALL_VALUES = {**FIELDS, **EXTRA}
DOCS = {doc["file_id"]: doc for doc in STATE["docs"]}


def test_three_status_values_are_all_present():
    """Seam promise: the three `status` values are trustworthy and `missing` is not a dead enum."""
    statuses = {value["status"] for value in ALL_VALUES.values()}
    assert statuses <= {"extracted", "inferred", "missing"}
    for expected in ("extracted", "inferred", "missing"):
        assert expected in statuses, f"the sample must cover {expected}"


def test_name_case_is_preserved():
    """Name-like fields keep the source case and spelling (the core promise of seam one)."""
    applicant = FIELDS["applicant_name"]
    assert applicant["value"] == "ABC Trading Pte Ltd"
    assert applicant["value"] != applicant["value"].upper()
    assert applicant["value"] == applicant["value"].strip()


def test_extracted_span_is_locatable_in_its_own_file():
    """An `extracted` field's `span` must be locatable in **the file_id it itself declares**."""
    for key, value in ALL_VALUES.items():
        if value["status"] != "extracted":
            continue
        source = value["source"]
        assert source is not None, f"{key} is marked extracted but has no source"
        text = normalize_ws(DOCS[source["file_id"]]["full_text"])
        assert normalize_ws(source["span"]) in text, f"{key} span cannot be found in the source"


def test_extracted_pdf_fields_have_page():
    """For PDF input, an `extracted` field MUST NOT always be `page=null`."""
    for key, value in ALL_VALUES.items():
        if value["status"] != "extracted":
            continue
        source = value["source"]
        doc = DOCS[source["file_id"]]
        if doc["form"] == "pdf_text":
            assert source["page"] is not None, f"{key} has an empty page, so the review console cannot jump back to the source"


def test_span_is_a_minimal_fragment():
    """`span` carries no field label and stays within the shared constant cap."""
    for key, value in ALL_VALUES.items():
        if not value["source"]:
            continue
        span = value["source"]["span"]
        assert span.strip() == span and span, f"{key} span is empty or has leading/trailing whitespace"
        assert len(span) <= MAX_SPAN_LEN, f"{key} span exceeds the cap (it should be downgraded to inferred)"
        for label in ("申请人：", "保函编号：", "币种：", "开立日期："):
            assert not span.startswith(label), f"{key} span contains the field label {label}"


def test_notes_is_always_a_list():
    """`notes` is always `[]`, never `null` (downstream iterates it directly)."""
    for key, value in ALL_VALUES.items():
        assert isinstance(value["notes"], list), f"{key} notes is not a list"


def test_undefined_fields_stay_in_extra_fields():
    """Fields outside the dictionary live in `extra_fields` only, never mixed into `fields`."""
    known = set(load_fields_config())
    assert known & set(EXTRA) == set(), "extra_fields contains keys already defined in fields.yaml"
    assert set(FIELDS) <= known


def test_fresh_fields_are_unconfirmed():
    """Fresh output is always `confirmed=false` / `edited_by_user=false`."""
    for key, value in ALL_VALUES.items():
        assert value["confirmed"] is False, f"{key} is confirmed although no human confirmed it"
        assert value["edited_by_user"] is False, f"{key} is edited_by_user although no human edited it"


def test_confidence_does_not_leak_into_contract():
    """`confidence` is not part of the contract (ranking inside extract only)."""
    for key, value in ALL_VALUES.items():
        assert "confidence" not in value, f"{key} leaks confidence"


def test_required_fields_are_all_present():
    """Every `required` field must exist in `fields` (placeholdered if absent), so downstream can tell "not written" from "not extracted"."""
    required = {key for key, fdef in load_fields_config().items() if fdef["required"]}
    missing = required - set(FIELDS)
    assert not missing, f"required fields missing from fields: {missing}"


def test_missing_placeholder_explains_itself():
    """A placeholder must state its reason (`not_in_source`), otherwise the review console cannot explain it."""
    missing_keys = [key for key, value in FIELDS.items() if value["status"] == "missing"]
    assert missing_keys, "the sample must contain a missing placeholder"
    for key in missing_keys:
        assert "not_in_source" in FIELDS[key]["notes"]
        assert FIELDS[key]["value"] is None
        assert FIELDS[key]["source"] is None


def test_downgraded_fields_are_not_marked_extracted():
    """A field carrying a downgrading note MUST NOT be `extracted`."""
    downgrading = {
        "date_ambiguous",
        "amount_not_numeric",
        "currency_not_iso4217",
        "value_truncated",
        "span_oversize",
        "merged_across_pages",
    }
    for key, value in ALL_VALUES.items():
        if downgrading & set(value["notes"]):
            assert value["status"] != "extracted", f"{key} carries a downgrading note but is marked extracted"


@pytest.mark.parametrize("key", ["guarantee_amount", "expiry_date"])
def test_inferred_and_missing_are_not_locatable(key):
    """When the span cannot be located, never claim it was."""
    assert FIELDS[key]["source"] is None
    assert FIELDS[key]["status"] in ("inferred", "missing")