"""Shared builders for graph/resume tests (no pytest fixtures, so imports cannot collide)."""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.findings import materialize_findings
from app.graph import build_graph
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
    """A stand-in for Agent 2: done + one non-blocking business finding."""
    draft = {
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
    materialized = materialize_findings(state, [draft], agent="agent2", stage="agent2")
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


def sample_source(tmp_path: Path) -> dict:
    path = tmp_path / "doc.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    return {
        "file_id": "F-1",
        "filename": path.name,
        "mime": "text/plain",
        "path": str(path),
        "sha256": "sha-1",
    }


def initial_state(tmp_path: Path) -> dict:
    return {
        "run_id": "R-test",
        "files": [sample_source(tmp_path)],
        "findings": [],
        "trail": [],
        "stages": [],
    }


def build_test_graph(llm=None, *, checkpointer=None, **kwargs):
    return build_graph(
        llm=llm or FakeLLM(),
        agent2=kwargs.pop("agent2", fake_agent2),
        retriever=kwargs.pop("retriever", FakeRetriever([CHUNK], CORPUS)),
        **kwargs,
    ).compile(checkpointer=checkpointer or InMemorySaver())
