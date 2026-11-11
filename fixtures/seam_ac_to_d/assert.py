"""Executable assertions for seam (A + C) -> D (agent-audit input).

Run from the repo root:
    .venv/Scripts/python.exe -m pytest fixtures/seam_ac_to_d/assert.py -q

Only assertions: Agent 4's verdict depends on its rule bundle, so a golden report would be
unstable. What must hold is that every extracted value points back into the file it declares,
and that no agent smuggled an overreach op into the trail.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.parsing.normalize import MAX_SPAN_LEN, normalize_ws, span_locatable
from app.state import FINDING_PREFIX, OVERREACH_OPS

STATE = json.loads(Path(__file__).with_name("input.json").read_text(encoding="utf-8"))
DOCS = {doc["file_id"]: doc for doc in STATE["docs"]}
FIELDS = STATE["fields"]


def test_every_document_has_a_stable_identity_and_verbatim_text():
    assert STATE["docs"]
    for doc in STATE["docs"]:
        assert doc["file_id"] and doc["sha256"]
        assert doc["errors"] == []
        joined = "\n".join(block["text"] for block in doc["blocks"])
        assert doc["full_text"] == joined, "full_text must be blocks joined in order"
        assert doc["full_text"].strip(), "a successful parse cannot have empty text"


def test_extracted_spans_are_locatable_in_the_declared_file():
    for key, value in FIELDS.items():
        if value["status"] != "extracted":
            continue
        source = value["source"]
        assert source is not None
        assert source["file_id"] in DOCS, f"{key} points at an unknown file"
        assert len(source["span"]) <= MAX_SPAN_LEN
        assert span_locatable(source, list(DOCS.values())), f"{key} span is not locatable"


def test_missing_values_have_no_source_and_inferred_are_not_claimed_as_extracted():
    for key, value in FIELDS.items():
        if value["status"] == "missing":
            assert value["source"] is None, f"{key}: a missing value cannot have a source"
        if value["status"] == "inferred":
            assert value["notes"], f"{key}: inferred values must say why"


def test_findings_use_the_contract_prefix_for_their_source():
    for finding in STATE["findings"]:
        prefix = FINDING_PREFIX[finding["source"]]
        assert finding["id"].startswith(f"{prefix}-")
        assert isinstance(finding["field_keys"], list)
        assert finding["resolved"] is False


def test_trail_ids_are_unique_and_no_overreach_op_exists():
    ids = [entry["id"] for entry in STATE["trail"]]
    assert len(ids) == len(set(ids))
    assert not [entry for entry in STATE["trail"] if entry["op"] in OVERREACH_OPS]


def test_business_type_is_decided_once_by_normalize():
    decisions = [
        entry
        for entry in STATE["trail"]
        if entry.get("detail", {}).get("business_type")
    ]
    assert len(decisions) == 1
    assert decisions[0]["stage"] == "normalize"


def test_legal_and_retrieved_are_self_describing():
    legal = STATE["legal"]
    assert legal["input_mode"] in ("raw", "enriched")
    assert isinstance(legal["coverage"]["unavailable"], bool)
    assert legal["coverage"]["unavailable"] is False
    for chunk in STATE["retrieved"]:
        assert chunk["source_type"] in ("kb", "web")
        assert chunk["chunk_id"] and chunk["doc_id"]


def test_required_stages_are_done_before_agent4_runs():
    done = {report["stage"] for report in STATE["stages"] if report["status"] == "done"}
    expected = {"ingest", "parse", "extract", "normalize", "agent2", "agent3", "audit"}
    assert expected <= done
    assert normalize_ws("URDG　758") == normalize_ws("URDG 758")
