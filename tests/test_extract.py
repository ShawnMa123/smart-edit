"""Extraction behavior (tasks 4.x): batching never splits a block, page backfill, retry, partial."""

from __future__ import annotations

from dataclasses import replace

from app.nodes.extract import extract_node
from app.parsing.extract import build_prompt, extract, locate_span
from app.parsing.extraction_profile import load_profile_by_id
from app.state import TRAIL_OPS
from tests.helpers import make_doc


def _cand(key: str, raw: str, span: str) -> dict:
    return {"key": key, "raw_value": raw, "span": span, "confidence": 0.9}


def test_prompt_contains_four_hard_rules():
    """The prompt carries the four hard rules: verbatim / smallest span / keep case / omit when absent (task 4.1)."""
    prompt = build_prompt("source fragment", ["guarantee_amount"])

    assert "verbatim" in prompt
    assert "smallest locatable fragment" in prompt
    assert "original case and spelling" in prompt
    assert "do not guess" in prompt


def test_candidate_carries_source_and_never_page_from_model():
    """Candidates carry `_source`, and `page` / `bbox` are located in the source by the system (tasks 4.2 / 4.5)."""
    doc = make_doc("AMOUNT: USD 500.00", page=2)
    result = extract([doc], ["guarantee_amount"], llm=lambda prompt: [_cand("guarantee_amount", "USD 500.00", "USD 500.00")])

    candidate = result.candidates[0]
    assert set(candidate) == {"key", "raw_value", "label", "confidence", "doc_type", "_source"}
    assert candidate["_source"]["file_id"] == "F-1"
    assert candidate["_source"]["page"] == 2
    assert candidate["_source"]["span"] == "USD 500.00"
    assert candidate["_source"]["form_label"] is None


def test_locate_span_returns_none_when_not_in_single_block():
    """Only a single-block hit counts; a cross-block span never gets a guessed bbox (task 4.5)."""
    doc = make_doc("保函金额 USD 500\nK 到期日 2027-01-01", page=1)
    assert locate_span(doc, "USD 500 K") == (None, None)
    assert locate_span(doc, "USD 500")[0] == 1


def test_batches_do_not_split_blocks():
    """Batches accumulate whole `blocks`, **never splitting a block** (task 4.4)."""
    doc = make_doc("A" * 60 + "\n" + "B" * 60 + "\n" + "C" * 60)
    seen: list[int] = []

    def llm(prompt: str):
        seen.append(prompt.count("A") + prompt.count("B") + prompt.count("C"))
        return []

    extract([doc], ["guarantee_amount"], llm=llm, batch_chars=100)

    assert len(seen) == 3, "one batch per block: the three blocks must not be merged or split"
    assert all(count >= 60 for count in seen), "no batch may contain a half-cut block"


def test_oversize_block_gets_its_own_batch_flag():
    """A single block over budget becomes its own batch, flagged `oversize_block` (task 4.4)."""
    doc = make_doc("X" * 200)
    result = extract([doc], ["guarantee_amount"], llm=lambda prompt: [], batch_chars=50)

    llm_calls = [entry for entry in result.trail_entries if entry["op"] == "llm_call"]
    assert len(llm_calls) == 1
    assert llm_calls[0]["detail"]["oversize_block"] is True
    assert result.model_calls == 1


def test_schema_violation_marks_stage_partial(fields_yaml, tmp_path):
    """A second failure lands in `failed_batches` and the node marks the stage `partial` (task 4.6)."""
    state = {"docs": [make_doc("AMOUNT: USD 500.00")], "trail": [], "stages": []}
    update = extract_node(state, llm=lambda prompt: {"unexpected": True}, field_keys=list(fields_yaml))

    report = update["stages"][0]
    assert report["status"] == "partial"
    assert "batch" in report["reason"]
    assert update["_candidates"] == []


def test_a_profile_runs_deterministically_without_any_provider(fields_yaml):
    """Task 2.4: profile selected -> no LLM needed, `model_calls=0`, provenance is recorded."""
    state = {
        "docs": [make_doc("保函金额：USD 500.00\n币种：USD\n开立日期：12/03/26")],
        "trail": [],
        "stages": [],
    }
    profile = load_profile_by_id("guarantee-default", fields_config=fields_yaml)

    update = extract_node(state, llm=None, profile=profile, fields_yaml=fields_yaml)

    report = update["stages"][0]
    assert report["status"] == "done"
    assert report["model_calls"] == 0
    assert report["reason"] == "deterministic profile guarantee-default@1.0.0"
    assert {candidate["key"] for candidate in update["_candidates"]} >= {
        "guarantee_amount",
        "currency",
        "issue_date",
    }
    assert update["_extraction"] == {
        "source": "deterministic",
        "profile_id": "guarantee-default",
        "version": "1.0.0",
        "content_sha256": profile.content_sha256,
        "document_types": ["guarantee"],
        "fields_found": 3,
        "fields_missing": 3,
        "llm_fallback": False,
    }
    assert all(entry["op"] in TRAIL_OPS for entry in update["trail"])


def test_without_a_profile_a_missing_provider_still_fails_loudly():
    """Task 2.4: the old path is unchanged; a profile must be explicit, never assumed."""
    update = extract_node({"docs": [make_doc("保函金额：USD 500.00")], "trail": [], "stages": []})

    assert update["stages"][0]["status"] == "failed"
    assert "no model provider" in update["stages"][0]["reason"]
    assert update["_extraction"] is None


def test_llm_fallback_is_opt_in_and_only_fills_missing_fields(fields_yaml):
    """Task 2.4 / spec: fallback candidates are unconfirmed and never override a deterministic hit."""
    state = {
        "docs": [make_doc("保函金额：USD 500.00")],
        "trail": [],
        "stages": [],
    }
    profile = replace(
        load_profile_by_id("guarantee-default", fields_config=fields_yaml),
        llm_fallback={"enabled": True},
    )

    def llm(prompt: str):
        return [
            _cand("guarantee_amount", "999.00", "999.00"),
            _cand("currency", "EUR", "EUR"),
        ]

    update = extract_node(state, llm=llm, profile=profile, fields_yaml=fields_yaml)

    by_key = {candidate["key"]: candidate for candidate in update["_candidates"]}
    assert by_key["guarantee_amount"]["raw_value"] == "USD 500.00", "deterministic hit is final"
    assert "status" not in by_key["guarantee_amount"]
    assert by_key["currency"]["raw_value"] == "EUR"
    assert by_key["currency"]["status"] == "unconfirmed"
    assert update["stages"][0]["model_calls"] > 0
    assert update["_extraction"]["llm_fallback"] is True


def test_extract_trail_ops_are_contract_values():
    """Every `op` in a receipt must be a contract enum value, otherwise `record_many` raises."""
    doc = make_doc("AMOUNT: USD 500.00")
    result = extract([doc], ["guarantee_amount"], llm=lambda prompt: [_cand("guarantee_amount", "USD 500.00", "USD 500.00")])

    assert {entry["op"] for entry in result.trail_entries} <= set(TRAIL_OPS)