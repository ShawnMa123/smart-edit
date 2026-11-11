"""HTTP acceptance for `POST /runs/{tid}/stages/agent3` with a fake retrieval service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.regulatory.retriever import FakeRetriever
from app.runs import RunStore

CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["CN"],
    "built_at": "2026-11-09T00:00:00Z",
}
CHUNK = {
    "chunk_id": "chunk-1",
    "doc_id": "cn-customs-guarantee-2018",
    "source_doc": "中华人民共和国海关事务担保条例",
    "title": "海关事务担保条例",
    "text": "第二条 当事人向海关申请提供担保，承诺履行法律义务。",
    "score": 0.9,
    "articles": ["第二条"],
    "effective_from": "2018-03-19",
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee"],
}


def test_agent3_trigger_returns_legal_retrieved_and_findings(tmp_path, monkeypatch):
    fake = FakeRetriever([CHUNK], CORPUS)
    monkeypatch.setattr("app.regulatory.node.resolve_retriever", lambda: fake)
    client = TestClient(create_app(store=RunStore(runs_dir=tmp_path / "runs"), llm=None))

    created = client.post("/runs", json={"text": "保函编号 BG-2026-0001\n适用规则 URDG 758"})
    assert created.status_code == 201
    thread_id = created.json()["thread_id"]

    response = client.post(f"/runs/{thread_id}/stages/agent3")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["legal"]["input_mode"] == "raw"
    assert body["legal"]["coverage"]["unavailable"] is False
    assert len(body["retrieved"]) == 1
    assert body["retrieved"][0]["chunk_id"] == "chunk-1"
    assert any(stage["stage"] == "agent3" and stage["agent"] == "agent3" for stage in body["stages"])
    regulatory = [finding for finding in body["findings"] if finding["source"] == "regulatory"]
    assert regulatory and all(finding["id"].startswith("R-") for finding in regulatory)
    assert "agent3" in body["supported_stages"]

    second = client.post(f"/runs/{thread_id}/stages/agent3").json()
    second_regulatory = [finding for finding in second["findings"] if finding["source"] == "regulatory"]
    assert [f["id"] for f in second_regulatory] == [f["id"] for f in regulatory], (
        "a rerun replaces the previous regulatory findings"
    )

    fetched = client.get(f"/runs/{thread_id}").json()
    assert fetched["legal"]["input_mode"] == "raw"
    assert fetched["retrieved"][0]["chunk_id"] == "chunk-1"
