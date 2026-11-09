"""Agent 3 registration and standalone-chain tests."""

from __future__ import annotations

from app.api.envelope import supported_stages
from app.regulatory.retriever import FakeRetriever
from app.runtime import execute_chain
from app.stages import AGENT_SPECS, AGENT_TARGETS, STAGE_TARGETS
from app.standalone import plan_standalone
from tests.helpers import make_doc

CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["AU", "CN", "US"],
    "built_at": "2026-11-09T00:00:00Z",
}
CHUNK = {
    "chunk_id": "chunk-1",
    "doc_id": "cn-customs-guarantee-2018",
    "source_doc": "中华人民共和国海关事务担保条例",
    "title": "海关事务担保条例",
    "text": "第464条 保函金额 USD 500,000.00 应当以书面形式约定。",
    "score": 0.9,
    "articles": ["第464条"],
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee"],
}


def _source(tmp_path) -> dict:
    path = tmp_path / "guarantee.txt"
    path.write_text("保函编号 BG-2026-0001\n金额 USD 500,000.00\n适用规则 URDG 758\n", encoding="utf-8")
    return {
        "file_id": "F-1",
        "filename": path.name,
        "mime": "text/plain",
        "path": str(path),
        "sha256": "sha-1",
    }


def _retriever() -> FakeRetriever:
    return FakeRetriever([CHUNK], CORPUS)


def test_agent3_is_a_registered_standalone_target():
    assert AGENT_SPECS["agent3"].standalone is True
    assert "agent3" in STAGE_TARGETS
    assert AGENT_TARGETS["agent3"] == "agent3"
    assert plan_standalone("agent3", {"files": [{"file_id": "F"}]})["status"] == 200


def test_agent3_raw_backfills_parse(tmp_path):
    state = {"files": [_source(tmp_path)], "findings": [], "trail": [], "stages": []}
    plan = plan_standalone("agent3", state)

    assert plan["chain"] == ["parse", "agent3"]
    execute_chain(state, plan["chain"], retriever=_retriever())

    assert any(report["stage"] == "parse" and report["status"] == "done" for report in state["stages"])
    assert state["legal"]["input_mode"] == "raw"
    assert state["docs"]


def test_agent3_enriched_uses_existing_normalize():
    doc = {**make_doc("保函编号 BG-2026-0001"), "sha256": "sha-1"}
    state = {
        "files": [
            {
                "file_id": "F-1",
                "filename": "F-1.txt",
                "mime": "text/plain",
                "path": "unused",
                "sha256": "sha-1",
            }
        ],
        "docs": [doc],
        "fields": {"guarantee_amount": {"key": "guarantee_amount", "value": "USD 500,000.00"}},
        "business_type": "guarantee",
        "stages": [
            {"stage": "normalize", "agent": "agent1", "status": "done", "reason": None, "produced": 1, "model_calls": 0}
        ],
        "findings": [],
        "trail": [],
    }

    execute_chain(state, plan_standalone("agent3", state)["chain"], retriever=_retriever())

    assert state["legal"]["input_mode"] == "enriched"
    parse_reports = [report for report in state["stages"] if report["stage"] == "parse"]
    assert len(parse_reports) == 1 and parse_reports[0]["status"] == "done"


def test_stage_report_agent_is_agent3(tmp_path):
    state = {"files": [_source(tmp_path)], "findings": [], "trail": [], "stages": []}
    execute_chain(state, ["parse", "agent3"], retriever=_retriever())

    report = [item for item in state["stages"] if item["stage"] == "agent3"][-1]
    assert report["agent"] == "agent3"
    assert report["status"] in {"done", "partial", "failed"}


def test_supported_stages_includes_agent3():
    assert "agent3" in supported_stages()
