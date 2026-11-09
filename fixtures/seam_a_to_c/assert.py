"""Executable assertions for seam A -> C (tasks 10.3 / 10.4).

The two promises A makes to Agent 3:
1. `docs[].full_text` is **verbatim** source text: not rewritten, not summarised
2. `business_type` is written into `EditState` by `normalize` only

How to run (from the repo root):
    .venv/bin/python -m pytest fixtures/seam_a_to_c/assert.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.parsing.normalize import normalize_ws

STATE = json.loads(Path(__file__).with_name("input.json").read_text(encoding="utf-8"))
DOCS = STATE["docs"]
FIELDS = STATE.get("fields", {})
BUSINESS_TYPES = ("guarantee", "unsupported")


def test_full_text_is_verbatim_concatenation_of_blocks():
    """`full_text` = blocks concatenated in order, verbatim (not a summary, not a paraphrase)."""
    assert DOCS
    for doc in DOCS:
        assert "\n".join(block["text"] for block in doc["blocks"]) == doc["full_text"]


def test_full_text_keeps_the_original_clause():
    """A long clause must be kept whole: summarising or rewriting makes Agent 3's citations miss the source."""
    doc = DOCS[0]
    clause = "本保函为见索即付独立保函，适用国际商会《见索即付保函统一规则》（URDG 758）。"
    assert clause in doc["full_text"], "the source clause was rewritten or summarised"
    assert "索赔须在到期日前以书面形式提交至开立银行。" in doc["full_text"]


def test_full_text_has_no_elision_markers():
    """No ellipsis or other summarisation markers may appear."""
    for doc in DOCS:
        for marker in ("...", "…", "(省略)", "（省略）", "摘要"):
            assert marker not in doc["full_text"], f"full_text contains a summarisation marker {marker}"


def test_parse_errors_are_explicit():
    """A parse failure must stay in `errors`, so Agent 3 can refuse to read an empty full text as "no issues"."""
    for doc in DOCS:
        assert isinstance(doc["errors"], list)
        if doc["errors"]:
            assert doc["full_text"] == "", "the parse failed yet a non-empty full text was returned"


def test_business_type_is_one_of_the_two_values():
    assert STATE["business_type"] in BUSINESS_TYPES


def test_business_type_written_only_by_normalize():
    """Single writer: `normalize`. `ingest` only passes it through, and Agent 3's raw mode writes `legal.coverage` only."""
    decisions = [
        entry
        for entry in STATE.get("trail", [])
        if entry.get("detail", {}).get("business_type")
    ]
    assert len(decisions) == 1, "the business_type decision must produce exactly one trail entry"
    assert decisions[0]["stage"] == "normalize"
    assert decisions[0]["agent"] == "agent1"


def test_business_type_decision_carries_evidence():
    """The evidence must be inspectable: `evidence` / `reason` cannot both be empty."""
    decision = next(
        entry for entry in STATE["trail"] if entry.get("detail", {}).get("business_type")
    )
    assert decision["detail"]["evidence"]
    assert decision["detail"]["reason"] in (
        "explicit_independence_clause",
        "explicit_keyword",
        "business_type_not_supported",
        "no_evidence",
    )


def test_agent1_does_not_write_agent3_keys():
    """A never writes Agent 3's conclusion keys — mixing them makes provenance unverifiable."""
    assert "legal" not in STATE
    assert "retrieved" not in STATE


@pytest.mark.parametrize("key", sorted(FIELDS))
def test_extracted_spans_are_locatable_in_full_text(key):
    """Every fragment Agent 3 cites must be findable in `full_text`."""
    value = FIELDS[key]
    if value["status"] != "extracted":
        pytest.skip("asserted for extracted fields only")
    doc = next(doc for doc in DOCS if doc["file_id"] == value["source"]["file_id"])
    assert normalize_ws(value["source"]["span"]) in normalize_ws(doc["full_text"])