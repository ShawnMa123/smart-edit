"""Value normalization + three-way classification (tasks 5.x, 2.3)."""

from __future__ import annotations

from app.findings import materialize_findings
from app.parsing.normalize import (
    MAX_SPAN_LEN,
    build_fields,
    classify,
    normalize_ws,
    shrink_span,
    span_locatable,
)
from tests.helpers import candidate, make_doc


def _build(candidates, docs, fields_yaml):
    return build_fields(candidates, docs, fields_yaml=fields_yaml)


# ---------------------------------------------------------------- value normalization §7.3


def test_amount_normalized_from_preserved(fields_yaml):
    """Amount -> 2 decimals, with `normalized_from` keeping the raw value (task 5.1)."""
    docs = [make_doc("保函金额：USD 500K")]
    result = _build([candidate("guarantee_amount", "USD 500K", "USD 500K")], docs, fields_yaml)
    field = result.fields["guarantee_amount"]

    assert field["value"] == "500000.00"
    assert field["normalized_from"] == "USD 500K"
    assert field["status"] == "extracted"


def test_amount_thousands_separator_and_decimal_type(fields_yaml):
    """Thousands separators are removed and `Decimal` leaves no float tail."""
    docs = [make_doc("保函金额：1,200,000.00")]
    result = _build(
        [candidate("guarantee_amount", "1,200,000.00", "1,200,000.00")], docs, fields_yaml
    )
    assert result.fields["guarantee_amount"]["value"] == "1200000.00"


def test_currency_iso4217(fields_yaml):
    """Currency -> ISO 4217, three upper-case letters (task 5.2)."""
    docs = [make_doc("币种：usd")]
    result = _build([candidate("currency", "usd", "usd")], docs, fields_yaml)
    field = result.fields["currency"]

    assert field["value"] == "USD"
    assert field["notes"] == []
    assert field["status"] == "extracted"


def test_date_order_dmy_resolves_without_note(fields_yaml):
    """With `date_order: DMY` declared, the value is read as DMY and not downgraded."""
    docs = [make_doc("开立日期：12/03/26")]
    result = _build([candidate("issue_date", "12/03/26", "12/03/26")], docs, fields_yaml)
    field = result.fields["issue_date"]

    assert field["value"] == "2026-03-12"
    assert field["notes"] == []
    assert field["status"] == "extracted"


def test_date_ambiguous_downgraded_to_inferred(fields_yaml):
    """With a null `date_order` we **must not pick an interpretation** (spec: ambiguous date)."""
    local = {**fields_yaml, "issue_date": {**fields_yaml["issue_date"], "date_order": None}}
    docs = [make_doc("开立日期：12/03/26")]
    result = _build([candidate("issue_date", "12/03/26", "12/03/26")], docs, local)
    field = result.fields["issue_date"]

    assert "date_ambiguous" in field["notes"]
    assert field["value"] == "12/03/26"
    assert field["status"] == "inferred"


def test_name_case_preserved(fields_yaml):
    """Name-like fields **keep the source case and spelling** (task 5.3 / seam one)."""
    docs = [make_doc("申请人：ABC Trading Pte Ltd")]
    result = _build(
        [candidate("applicant_name", " ABC Trading Pte Ltd ", "ABC Trading Pte Ltd")],
        docs,
        fields_yaml,
    )
    field = result.fields["applicant_name"]

    assert field["value"] == "ABC Trading Pte Ltd"
    assert field["status"] == "extracted"


def test_integer_strips_unit_suffix(fields_yaml):
    docs = [make_doc("期限：720 DAYS")]
    result = _build([candidate("tenor_days", "720 DAYS", "720 DAYS")], docs, fields_yaml)
    assert result.fields["tenor_days"]["value"] == "720"


# ---------------------------------------------------------------- normalize_ws benchmark §7.1


def test_normalize_ws_nfkc_dashes_quotes():
    """Full/half width, `U+2011`, curly quotes, zero-width chars, multi-line whitespace (task 2.3)."""
    assert normalize_ws("９００‑１２３４") == "900-1234"
    assert normalize_ws("“ABC” Trading") == '"ABC" Trading'
    assert normalize_ws("AB\u200bC") == "ABC"
    assert normalize_ws("申请人：\nABC") == "申请人: ABC"
    assert normalize_ws("　全角空格　") == "全角空格"


def test_normalize_ws_does_not_fold_case():
    """**No** case folding: a case difference means the model did not copy verbatim."""
    assert normalize_ws("ABC Trading") != normalize_ws("abc trading")


def test_span_whitespace_normalized_match(fields_yaml):
    """A multi-line span must be locatable after whitespace normalization (otherwise fields downgrade in batches)."""
    docs = [make_doc("申请人：ABC Trading\nPte Ltd")]
    result = _build(
        [candidate("applicant_name", "ABC Trading Pte Ltd", "ABC Trading Pte Ltd")],
        docs,
        fields_yaml,
    )
    assert result.fields["applicant_name"]["status"] == "extracted"


def test_span_not_found_becomes_inferred(fields_yaml):
    """A value the model returned is not in the source -> `inferred` + `source=None`."""
    docs = [make_doc("申请人：ABC Trading Pte Ltd")]
    result = _build(
        [candidate("applicant_name", "ACME CORP", "ACME CORP")], docs, fields_yaml
    )
    field = result.fields["applicant_name"]

    assert field["status"] == "inferred"
    assert field["source"] is None
    assert field["confirmed"] is False


def test_span_found_in_other_file_becomes_inferred(fields_yaml):
    """**No cross-file locating**: text found in another file does not count as `extracted` (task 5.4)."""
    docs = [make_doc("unrelated content", file_id="F-1"), make_doc("申请人：ABC Trading Pte Ltd", file_id="F-2")]
    result = _build(
        [candidate("applicant_name", "ABC Trading Pte Ltd", "ABC Trading Pte Ltd", file_id="F-1")],
        docs,
        fields_yaml,
    )
    assert result.fields["applicant_name"]["status"] == "inferred"


def test_span_locatable_is_single_file_only():
    src = {"file_id": "F-1", "span": "ABC"}
    docs = [{"file_id": "F-2", "full_text": "ABC"}]
    assert span_locatable(src, docs) is False


# ---------------------------------------------------------------- truncation and Finding §7.5


def test_oversize_field_truncated_with_finding(fields_yaml):
    """Over `max_length` -> truncate + `value_truncated` + `inferred` + Finding draft (task 5.7)."""
    long_value = "BG-" + "9" * 70
    docs = [make_doc(f"保函编号：{long_value}")]
    result = _build([candidate("guarantee_number", long_value, long_value)], docs, fields_yaml)
    field = result.fields["guarantee_number"]

    assert len(field["value"]) == 64
    assert "value_truncated" in field["notes"]
    assert field["status"] == "inferred"
    assert len(result.findings) == 1
    draft = result.findings[0]
    assert "id" not in draft, "the pure function does not number; materialize_findings assigns the id"
    assert draft["rule_id"] == "F-guarantee_number-max_length"
    assert draft["blocking"] is False
    assert draft["field_keys"] == ["guarantee_number"]


def test_finding_ids_continue_after_rerun():
    """Numbering continues: a rerun never reuses an existing Finding id (task 6.2)."""
    draft = {
        "source": "normalization",
        "kind": "invalid_value",
        "rule_id": "F-x-max_length",
        "severity": "warn",
        "blocking": False,
        "resolved": False,
        "resolution": None,
        "field_keys": ["x"],
        "message": "x is too long",
        "evidence": "x",
        "citation": None,
        "suggestion": None,
    }
    first = materialize_findings({"findings": []}, [draft])
    assert first["findings"][0]["id"] == "N-001"
    second = materialize_findings({"findings": first["findings"]}, [draft])
    assert second["findings"][0]["id"] == "N-002"
    assert second["trail"][0]["op"] == "emit"


def test_oversize_amount_truncated_and_flagged(fields_yaml):
    """11.9 Over-long amount: truncation + `value_truncated` + `N-` Finding all happen together."""
    long_amount = "1" * 22
    docs = [make_doc(f"保函金额：{long_amount}")]
    result = _build([candidate("guarantee_amount", long_amount, long_amount)], docs, fields_yaml)
    field = result.fields["guarantee_amount"]

    assert len(field["value"]) == 18
    assert "value_truncated" in field["notes"]
    assert field["status"] == "inferred"

    materialized = materialize_findings({"findings": []}, result.findings)
    assert materialized["findings"][0]["id"] == "N-001"
    assert materialized["findings"][0]["rule_id"] == "F-guarantee_amount-max_length"


def test_finding_initial_state_is_fixed():
    """`blocking`/`resolved` are always `false`, `resolution` always `null`, and an `emit` entry is mandatory (tasks 6.3/6.4)."""
    draft = {
        "source": "normalization",
        "kind": "invalid_value",
        "rule_id": "F-guarantee_number-max_length",
        "severity": "warn",
        "blocking": False,
        "resolved": False,
        "resolution": None,
        "field_keys": ["guarantee_number"],
        "message": "truncated",
        "evidence": "BG-2026-0001",
        "citation": None,
        "suggestion": None,
    }
    materialized = materialize_findings({"findings": []}, [draft])
    finding = materialized["findings"][0]

    assert finding["id"] == "N-001"
    assert finding["source"] == "normalization"
    assert finding["kind"] == "invalid_value"
    assert finding["blocking"] is False
    assert finding["resolved"] is False
    assert finding["resolution"] is None

    emit = materialized["trail"][0]
    assert emit["op"] == "emit"
    assert emit["after"] == "N-001"
    assert emit["ref"] == "guarantee_number"
    assert emit["detail"]["rule_id"] == draft["rule_id"]


# ---------------------------------------------------------------- missing placeholder §7.4


def test_required_missing_gets_placeholder(fields_yaml):
    """A `required` field without candidates -> placeholder + `not_in_source` + `op="pass"` (task 5.6)."""
    docs = [make_doc("保函编号：BG-2026-0001")]
    result = _build(
        [candidate("guarantee_number", "BG-2026-0001", "BG-2026-0001")], docs, fields_yaml
    )
    placeholder = result.fields["guarantee_amount"]

    assert placeholder["status"] == "missing"
    assert placeholder["value"] is None
    assert placeholder["notes"] == ["not_in_source"]
    assert placeholder["source"] is None
    assert result.findings == [], "a placeholder produces no Finding: blocking is Agent 2's call"

    passes = [
        entry
        for entry in result.trail_entries
        if entry["op"] == "pass" and entry["detail"].get("key") == "guarantee_amount"
    ]
    assert passes, "every placeholder must write one pass entry"
    assert passes[0]["detail"]["reason"] == "field not present in source"


def test_optional_missing_not_present(fields_yaml):
    """Missing optional fields get no placeholder (placeholders would flood the review console)."""
    docs = [make_doc("保函编号：BG-2026-0001")]
    result = _build([], docs, fields_yaml)
    assert "guarantee_type" not in result.fields
    assert "issuing_bank" not in result.fields


# ---------------------------------------------------------------- fields outside the dictionary / contract edges


def test_undefined_field_goes_to_extra_fields(fields_yaml):
    """Fields outside the dictionary go to `extra_fields` only, never mixed into `fields` (task 5.8)."""
    docs = [make_doc("备注：客户要求周五前回签")]
    result = _build(
        [candidate("custom_memo", "客户要求周五前回签", "客户要求周五前回签")], docs, fields_yaml
    )

    assert "custom_memo" not in result.fields
    assert result.extra_fields["custom_memo"]["value"] == "客户要求周五前回签"


def test_confidence_never_reaches_field_value(fields_yaml):
    """`confidence` must not be written into `FieldValue` (the contract has no such field, task 4.8)."""
    docs = [make_doc("保函编号：BG-2026-0001")]
    result = _build(
        [candidate("guarantee_number", "BG-2026-0001", "BG-2026-0001", confidence=0.42)],
        docs,
        fields_yaml,
    )
    assert "confidence" not in result.fields["guarantee_number"]


# ---------------------------------------------------------------- span cap and cross-page §7.2


def test_shrink_span_cuts_at_sentence_end():
    span = "A" * 100 + "。" + "B" * 200
    shrunk = shrink_span(span)
    assert shrunk is not None
    assert len(shrunk) <= MAX_SPAN_LEN
    assert shrunk.endswith("。")


def test_shrink_span_returns_none_for_single_long_sentence():
    assert shrink_span("A" * (MAX_SPAN_LEN + 10)) is None


def test_span_oversize_downgrade(fields_yaml):
    """A single sentence over 200 -> `span_oversize` + `inferred`, and the **span itself is not truncated** (task 5.11)."""
    long_span = "A" * (MAX_SPAN_LEN + 60)
    docs = [make_doc(long_span)]
    result = _build([candidate("custom_memo", long_span, long_span)], docs, fields_yaml)
    field = result.extra_fields["custom_memo"]

    assert "span_oversize" in field["notes"]
    assert field["status"] == "inferred"
    assert len(field["source"]["span"]) > MAX_SPAN_LEN, "the value gets truncated, the provenance does not"


def test_cross_page_span_downgrade(fields_yaml):
    """Cross-page stitching -> `merged_across_pages` + `transform` + `cross_page` + `inferred` (task 5.10)."""
    doc = {
        "file_id": "F-1",
        "filename": "F-1.pdf",
        "mime": "application/pdf",
        "form": "pdf_text",
        "blocks": [
            {
                "file_id": "F-1",
                "page": 1,
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "text": "保函金额 USD 500",
                "kind": "paragraph",
            },
            {
                "file_id": "F-1",
                "page": 2,
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "text": "K 到期日 2027-01-01",
                "kind": "paragraph",
            },
        ],
        "full_text": "保函金额 USD 500\nK 到期日 2027-01-01",
        "errors": [],
    }
    result = _build(
        [candidate("guarantee_amount", "USD 500 K", "USD 500 K", page=1)], [doc], fields_yaml
    )
    field = result.fields["guarantee_amount"]

    assert "merged_across_pages" in field["notes"]
    assert field["status"] == "inferred"
    cross = [
        entry
        for entry in result.trail_entries
        if entry["op"] == "transform" and entry["detail"].get("cross_page")
    ]
    assert cross and cross[0]["detail"]["pages"] == [1, 2]


# ---------------------------------------------------------------- only normalize-stage constraints §7.7


def test_only_normalize_stage_constraints_are_executed(fields_yaml):
    """`positive` belongs to `stage.validate` (executed by B); A **must not** judge on it (task 5.9)."""
    docs = [make_doc("保函金额：-5")]
    result = _build([candidate("guarantee_amount", "-5", "-5")], docs, fields_yaml)
    field = result.fields["guarantee_amount"]

    assert field["notes"] == []
    assert field["status"] == "extracted"
    assert result.findings == []


def test_classify_has_only_three_branches():
    assert classify(None, True, []) == "missing"
    assert classify("", True, []) == "missing"
    assert classify("500000.00", True, []) == "extracted"
    assert classify("500000.00", False, []) == "inferred"
    assert classify("500000.00", True, ["date_ambiguous"]) == "inferred"