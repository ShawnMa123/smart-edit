"""Runtime seams (tasks 1.1-1.5)."""

from __future__ import annotations

from app.config import load_fields_config
from app.nodes.extract import extract_node
from app.nodes.normalize import normalize_node
from app.nodes.parse import parse_node
from app.runtime import UnknownStage, execute_chain, is_done, merge_update
from tests.helpers import apply_update


def _source(tmp_path) -> dict:
    doc = tmp_path / "memo.txt"
    doc.write_text(
        "Guarantee No: BG-2026-00417\nAmount: USD 500,000.00\nApplicant: Alpha Tech Pte Ltd\n",
        encoding="utf-8",
    )
    return {
        "file_id": "F-1",
        "filename": doc.name,
        "mime": "text/plain",
        "path": str(doc),
        "sha256": "abc",
    }


def _state(tmp_path) -> dict:
    return {
        "run_id": "R-1",
        "files": [_source(tmp_path)],
        "trail": [],
        "stages": [],
        "findings": [],
    }


def _stub_llm(prompt=None):  # noqa: ARG001
    return [
        {
            "key": "guarantee_amount",
            "raw_value": "USD 500,000.00",
            "span": "USD 500,000.00",
            "confidence": 0.9,
        }
    ]


def test_merge_update_appends_reducer_keys_only():
    """1.1 Reducer keys append; everything else overwrites."""
    state = {"stages": [{"stage": "parse"}], "trail": [{"id": "t1"}], "findings": [], "docs": [1]}
    merge_update(
        state,
        {
            "stages": [{"stage": "extract"}],
            "trail": [{"id": "t2"}],
            "findings": [{"id": "N-001"}],
            "docs": [2],
        },
    )

    assert [report["stage"] for report in state["stages"]] == ["parse", "extract"]
    assert [entry["id"] for entry in state["trail"]] == ["t1", "t2"]
    assert [finding["id"] for finding in state["findings"]] == ["N-001"]
    assert state["docs"] == [2], "non-reducer keys overwrite"


def test_merge_update_overwrites_candidates():
    """1.1 `_candidates` is not a reducer key: normalize must be able to clear it."""
    state = {"_candidates": [{"key": "guarantee_amount"}]}
    merge_update(state, {"_candidates": []})
    assert state["_candidates"] == []


def test_execute_chain_matches_manual_merge(tmp_path):
    """1.3 The chain executor yields the same state as merging node updates by hand."""
    fields = load_fields_config()
    chained = execute_chain(_state(tmp_path), ["parse", "extract", "normalize"], llm=_stub_llm)

    manual = _state(tmp_path)
    apply_update(manual, parse_node(manual))
    apply_update(manual, extract_node(manual, llm=_stub_llm, field_keys=list(fields)))
    apply_update(manual, normalize_node(manual, fields_yaml=fields))

    assert [(r["stage"], r["status"]) for r in chained["stages"]] == [
        (r["stage"], r["status"]) for r in manual["stages"]
    ]
    assert {k: v["status"] for k, v in chained["fields"].items()} == {
        k: v["status"] for k, v in manual["fields"].items()
    }
    assert [entry["op"] for entry in chained["trail"]] == [entry["op"] for entry in manual["trail"]]


def test_second_run_skips_done_stages(tmp_path):
    """1.4 A stage whose latest report is done is not re-executed."""
    state = execute_chain(_state(tmp_path), ["parse", "extract", "normalize"], llm=_stub_llm)
    fields_before = dict(state["fields"])
    stages_before = len(state["stages"])

    execute_chain(state, ["parse", "extract", "normalize"], llm=_stub_llm)

    assert len(state["stages"]) == stages_before, "no stage may be re-executed"
    assert state["fields"] == fields_before, "a repeat click must not rebuild fields from nothing"
    assert state["fields"]["guarantee_amount"]["status"] == "extracted"


def test_unknown_stage_raises_before_any_node_runs(tmp_path):
    """1.5 An unregistered name raises and leaves the state untouched."""
    state = _state(tmp_path)
    before = dict(state)

    try:
        execute_chain(state, ["parse", "bogus"], llm=_stub_llm)
    except UnknownStage as exc:
        assert "bogus" in str(exc)
    else:  # pragma: no cover - the raise is the whole point
        raise AssertionError("expected UnknownStage")

    assert state == before, "no node may run before the chain is validated"


def test_is_done_reads_latest_report():
    state = {"stages": [{"stage": "parse", "status": "done"}, {"stage": "parse", "status": "failed"}]}
    assert is_done(state, "parse") is False, "the latest report wins"
    assert is_done(state, "extract") is False