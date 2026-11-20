"""Deterministic extraction (change: config-driven-audit-extraction, tasks 2.1-2.3)."""

from __future__ import annotations

from app.parsing.deterministic_extract import extract_deterministic
from app.parsing.extraction_profile import load_profile_by_id
from app.parsing.normalize import build_fields, normalize_field_value
from tests.helpers import make_doc

SAMPLE = """保函编号：BG-2026-0001
保函金额：USD 500,000.00
币种：usd
开立日期：12/03/26
到期日：2027-03-12
适用规则：URDG 758
付款条件：
Payment shall be made in USD within 30 days of presentation."""


def _profile(fields_yaml):
    return load_profile_by_id("guarantee-default", fields_config=fields_yaml)


def test_extracts_amount_date_currency_and_text_from_the_current_document(fields_yaml):
    result = extract_deterministic([make_doc(SAMPLE)], _profile(fields_yaml), fields_yaml)

    by_key = {candidate["key"]: candidate for candidate in result.candidates}
    assert set(by_key) == {
        "guarantee_amount",
        "currency",
        "issue_date",
        "expiry_date",
        "governing_rules",
        "payment_terms",
    }
    assert by_key["guarantee_amount"]["raw_value"] == "USD 500,000.00"
    assert by_key["guarantee_amount"]["_source"]["span"] == "USD 500,000.00"
    assert "保函金额" not in by_key["guarantee_amount"]["_source"]["span"]
    assert by_key["currency"]["raw_value"] == "usd"
    assert by_key["issue_date"]["raw_value"] == "12/03/26"
    assert by_key["governing_rules"]["raw_value"] == "URDG 758"
    assert by_key["payment_terms"]["raw_value"].startswith("Payment shall be made")
    assert by_key["payment_terms"]["_match"]["via"] == "next_block"
    assert result.model_calls == 0
    assert result.missing == ()


def test_normalization_reuses_the_single_implementation(fields_yaml):
    """Task 2.2: `12/03/26` and `USD 500,000.00` normalize exactly as `normalize` does."""
    profile = _profile(fields_yaml)
    result = extract_deterministic([make_doc(SAMPLE)], profile, fields_yaml)
    by_key = {candidate["key"]: candidate for candidate in result.candidates}

    date_value, _ = normalize_field_value("issue_date", by_key["issue_date"]["raw_value"], fields_yaml["issue_date"])
    amount_value, _ = normalize_field_value(
        "guarantee_amount", by_key["guarantee_amount"]["raw_value"], fields_yaml["guarantee_amount"]
    )

    assert date_value == "2026-03-12"
    assert amount_value == "500000.00"


def test_value_on_the_next_block_keeps_its_own_source(fields_yaml):
    doc = make_doc("到期日：\n2027-03-12", page=2)
    result = extract_deterministic([doc], _profile(fields_yaml), fields_yaml)

    candidate = next(item for item in result.candidates if item["key"] == "expiry_date")
    assert candidate["raw_value"] == "2027-03-12"
    assert candidate["_source"]["page"] == 2
    assert candidate["_source"]["span"] == "2027-03-12"


def test_cross_page_label_and_value_is_never_stitched(fields_yaml):
    blocks = [
        {"file_id": "F-1", "page": 1, "bbox": None, "text": "到期日：", "kind": "paragraph"},
        {"file_id": "F-1", "page": 2, "bbox": None, "text": "2027-03-12", "kind": "paragraph"},
    ]
    doc = {
        "file_id": "F-1",
        "filename": "F-1.txt",
        "mime": "text/plain",
        "form": "plain_text",
        "blocks": blocks,
        "full_text": "到期日：\n2027-03-12",
        "errors": [],
    }
    result = extract_deterministic([doc], _profile(fields_yaml), fields_yaml)

    assert not any(item["key"] == "expiry_date" for item in result.candidates)
    assert any(
        entry["detail"].get("reason") == "cross_page_label_value_skipped" for entry in result.trail_entries
    )


def test_duplicate_values_are_de_duplicated_with_a_receipt(fields_yaml):
    text = "保函金额：USD 500.00\n保函金额：USD 500.00"
    result = extract_deterministic([make_doc(text)], _profile(fields_yaml), fields_yaml)

    candidates = [item for item in result.candidates if item["key"] == "guarantee_amount"]
    assert len(candidates) == 1
    assert any(
        entry["detail"].get("reason") == "duplicate_value_ignored" for entry in result.trail_entries
    )


def test_different_values_are_marked_conflicted_and_reach_normalize_as_inferred(fields_yaml):
    text = "保函金额：USD 500.00\n金额：USD 600.00"
    result = extract_deterministic([make_doc(text)], _profile(fields_yaml), fields_yaml)

    candidates = [item for item in result.candidates if item["key"] == "guarantee_amount"]
    assert len(candidates) == 1
    assert candidates[0]["conflicted"] is True
    assert candidates[0]["status"] == "unconfirmed"
    assert len(candidates[0]["conflict_values"]) == 2
    ambiguous = [
        entry for entry in result.trail_entries if entry["detail"].get("reason") == "ambiguous_extraction"
    ]
    assert ambiguous and len(ambiguous[0]["detail"]["values"]) == 2

    normalized = build_fields(result.candidates, [make_doc(text)], fields_yaml=fields_yaml)
    field = normalized.fields["guarantee_amount"]
    assert field["status"] == "inferred"
    assert "extraction_conflict" in field["notes"]


def test_missing_label_never_invents_a_candidate(fields_yaml):
    result = extract_deterministic([make_doc("nothing to see here")], _profile(fields_yaml), fields_yaml)

    assert result.candidates == []
    assert set(result.missing) == {
        "guarantee_amount",
        "currency",
        "issue_date",
        "expiry_date",
        "governing_rules",
        "payment_terms",
    }


def test_negative_amount_keeps_its_sign(fields_yaml):
    """The value span must not lose a leading `-` (task 5.3 audits negative amounts)."""
    result = extract_deterministic([make_doc("保函金额：-500.00")], _profile(fields_yaml), fields_yaml)

    candidate = next(item for item in result.candidates if item["key"] == "guarantee_amount")
    assert candidate["raw_value"] == "-500.00"
    assert candidate["_source"]["span"] == "-500.00"


def test_alias_word_inside_prose_is_not_a_second_value(fields_yaml):
    """`PAYMENT` starts the sentence that is the *value* of `付款条件`; it is not a label."""
    text = "付款条件：\nPayment shall be made in USD within 30 days of presentation."
    result = extract_deterministic([make_doc(text)], _profile(fields_yaml), fields_yaml)

    candidate = next(item for item in result.candidates if item["key"] == "payment_terms")
    assert candidate["raw_value"] == "Payment shall be made in USD within 30 days of presentation."
    assert candidate.get("conflicted") is None
    assert len([item for item in result.candidates if item["key"] == "payment_terms"]) == 1


def test_chinese_copula_separates_label_and_value(fields_yaml):
    text = "本保函金额为USD 500.00，币种为USD，开立日期为2026年3月12日。"
    result = extract_deterministic([make_doc(text)], _profile(fields_yaml), fields_yaml)

    by_key = {item["key"]: item for item in result.candidates}
    assert by_key["guarantee_amount"]["raw_value"] == "USD 500.00"
    assert by_key["currency"]["raw_value"] == "USD"
    assert by_key["issue_date"]["raw_value"] == "2026年3月12日"


def test_values_stop_at_their_own_line_inside_one_paragraph_block(fields_yaml):
    """`parse` joins consecutive plain-text lines into one block; a value must not eat the next line."""
    block = {
        "file_id": "F-1",
        "page": None,
        "bbox": None,
        "kind": "paragraph",
        "text": (
            "保函金额：USD 500,000.00\n"
            "币种：USD\n"
            "开立日期：2026-11-20\n"
            "到期日：2027-11-20\n"
            "适用规则：URDG 758\n"
            "付款条件：\n"
            "Payment shall be made in USD within 30 days of presentation."
        ),
    }
    doc = {
        "file_id": "F-1",
        "filename": "F-1.txt",
        "mime": "text/plain",
        "form": "plain_text",
        "blocks": [block],
        "full_text": block["text"],
        "errors": [],
    }

    result = extract_deterministic([doc], _profile(fields_yaml), fields_yaml)
    by_key = {item["key"]: item for item in result.candidates}

    assert by_key["governing_rules"]["raw_value"] == "URDG 758"
    assert by_key["payment_terms"]["raw_value"] == (
        "Payment shall be made in USD within 30 days of presentation."
    )
    normalized = build_fields(result.candidates, [doc], fields_yaml=fields_yaml)
    assert normalized.fields["governing_rules"]["value"] == "URDG 758"
    assert "value_truncated" not in normalized.fields["governing_rules"]["notes"]
