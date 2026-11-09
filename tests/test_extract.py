"""Extraction behavior (tasks 4.x): batching never splits a block, page backfill, retry, partial."""

from __future__ import annotations

from app.nodes.extract import extract_node
from app.parsing.extract import build_prompt, extract, locate_span
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


def test_extract_trail_ops_are_contract_values():
    """Every `op` in a receipt must be a contract enum value, otherwise `record_many` raises."""
    doc = make_doc("AMOUNT: USD 500.00")
    result = extract([doc], ["guarantee_amount"], llm=lambda prompt: [_cand("guarantee_amount", "USD 500.00", "USD 500.00")])

    assert {entry["op"] for entry in result.trail_entries} <= set(TRAIL_OPS)