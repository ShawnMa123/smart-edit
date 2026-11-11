"""Main graph reaches the review interrupt with a self-contained payload (tasks 8.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import build_graph
from app.nodes.merge import merge_findings, merge_node
from app.regulatory.retriever import FakeRetriever
from app.stages import stage_report
from app.trail import record

SAMPLE = (
    "保函编号：BG-2026-0001\n"
    "币种：USD\n"
    "申请人：ABC Trading Pte Ltd\n"
    "开立日期：2026-03-12\n"
)
CORPUS = {
    "version": "test",
    "documents": 1,
    "jurisdictions": ["CN"],
    "built_at": "2026-11-09T00:00:00Z",
}
CHUNK = {
    "chunk_id": "c1",
    "doc_id": "doc-1",
    "title": "担保条例",
    "text": "保函应当以书面形式约定。",
    "score": 0.9,
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee"],
}


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.provider = "test"

    def __call__(self, prompt: str):  # noqa: ARG002
        self.calls += 1
        return [
            {
                "key": "guarantee_number",
                "raw_value": "BG-2026-0001",
                "span": "BG-2026-0001",
                "confidence": 0.9,
            },
            {"key": "currency", "raw_value": "USD", "span": "USD", "confidence": 0.9},
            {
                "key": "applicant_name",
                "raw_value": "ABC Trading Pte Ltd",
                "span": "ABC Trading Pte Ltd",
                "confidence": 0.9,
            },
            {
                "key": "issue_date",
                "raw_value": "2026-03-12",
                "span": "2026-03-12",
                "confidence": 0.9,
            },
        ]


def fake_agent2(state: dict) -> dict:
    """A stand-in for the owned-by-another-change verifier: done + one business finding."""
    finding = {
        "source": "business",
        "kind": "invalid_value",
        "rule_id": "TEST-RULE",
        "severity": "warn",
        "blocking": False,
        "resolved": False,
        "resolution": None,
        "field_keys": ["currency"],
        "message": "test finding",
        "evidence": "USD",
        "citation": None,
        "suggestion": None,
    }
    from app.findings import materialize_findings

    materialized = materialize_findings(state, [finding], agent="agent2", stage="agent2")
    return {
        "findings": materialized["findings"],
        "stages": [
            stage_report("agent2", status="done", produced=1, model_calls=0, agent="agent2")
        ],
        **record(
            state,
            agent="agent2",
            stage="agent2",
            op="pass",
            detail={"reason": "test stand-in"},
        ),
    }


def _source(tmp_path: Path) -> dict:
    path = tmp_path / "doc.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    return {
        "file_id": "F-1",
        "filename": path.name,
        "mime": "text/plain",
        "path": str(path),
        "sha256": "sha-1",
    }


def _graph(tmp_path: Path, *, llm=None):
    return build_graph(
        llm=llm or FakeLLM(),
        agent2=fake_agent2,
        retriever=FakeRetriever([CHUNK], CORPUS),
    ).compile(checkpointer=InMemorySaver())


def _state(tmp_path: Path) -> dict:
    return {
        "run_id": "R-test",
        "files": [_source(tmp_path)],
        "findings": [],
        "trail": [],
        "stages": [],
    }


def test_graph_reaches_hitl_with_a_self_contained_payload(tmp_path):
    graph = _graph(tmp_path)
    config = {"configurable": {"thread_id": "flow-1"}}
    result = graph.invoke(_state(tmp_path), config)

    interrupts = result.get("__interrupt__") or ()
    assert interrupts, "the graph must pause at hitl"
    payload = interrupts[0].value
    assert set(payload) == {
        "run_id",
        "business_type",
        "fields",
        "findings",
        "legal",
        "verification",
        "stages",
    }
    assert [field["key"] for field in payload["fields"]] == sorted(
        field["key"] for field in payload["fields"]
    )
    assert payload["fields"], "normalize produced fields"
    assert payload["stages"], "the panel can see what ran"

    state = graph.get_state(config)
    assert state.next == ("hitl",)
    stages = [report["stage"] for report in state.values["stages"]]
    for stage in ("ingest", "parse", "extract", "normalize", "reset", "agent2", "agent3", "merge", "audit"):
        assert stage in stages, f"{stage} did not run"


def test_merge_dedupes_without_renumbering_and_orders_by_severity():
    def finding(fid, source, severity, blocking, evidence):
        return {
            "id": fid,
            "source": source,
            "rule_id": "R",
            "field_keys": ["f"],
            "evidence": evidence,
            "severity": severity,
            "blocking": blocking,
        }

    duplicates = [
        finding("B-002", "business", "info", False, "b2"),
        finding("B-001", "business", "critical", True, "b1"),
        finding("R-001", "regulatory", "warn", True, "r1"),
    ]
    merged = merge_findings(duplicates + [duplicates[1]])
    assert [item["id"] for item in merged] == ["B-001", "R-001", "B-002"]

    update = merge_node({"findings": duplicates})
    assert update["stages"][0]["stage"] == "merge"
    assert update["stages"][0]["produced"] == 3


def test_merge_rejects_a_finding_whose_prefix_does_not_match_its_source():
    bad = {
        "id": "R-001",
        "source": "business",
        "rule_id": "R",
        "field_keys": [],
        "evidence": None,
        "severity": "warn",
        "blocking": False,
    }
    with pytest.raises(ValueError):
        merge_findings([bad])


def test_graph_does_not_reinvoke_a_completed_thread(tmp_path):
    """A second `start` observes the checkpoint instead of replaying model calls."""
    from app.runs import RunStore
    from app.runner import Runner
    from app.store import RunStore as Ledger

    llm = FakeLLM()
    runs = RunStore(runs_dir=tmp_path / "runs")
    thread_id, state = runs.create()
    state["files"] = [_source(tmp_path)]
    runner = Runner(
        runs,
        graph=_graph(tmp_path, llm=llm),
        ledger=Ledger(tmp_path / "ledger.sqlite"),
    )
    first = runner.start(thread_id)
    assert first["status"] == "interrupted"
    calls = llm.calls
    second = runner.start(thread_id)
    assert second["status"] == "interrupted"
    assert llm.calls == calls
