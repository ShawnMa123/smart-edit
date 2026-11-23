"""Answer provenance: route + web summary (assistant-answer-provenance / design D4–D5)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.assistant.egress import EgressPolicy
from app.assistant.gateway import DoubaoGateway
from app.assistant.settings import AssistantSettings
from tests.assistant_helpers import (
    WORKSPACE,
    headers,
    make_client,
    make_services,
    register_snapshot,
)


def _session(client, body: dict | None = None) -> dict:
    response = client.post(
        "/assistant/sessions",
        json=body or {"workspace_id": WORKSPACE, "locale": "en"},
        headers=headers("user_a", "sess"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run(client, session_id: str, question: str, *, web: bool = False, **kwargs) -> dict:
    accepted = client.post(
        f"/assistant/sessions/{session_id}/runs",
        json={"question": question, "web_search": web, **kwargs},
        headers=headers("user_a", "run-1"),
    )
    assert accepted.status_code == 202, accepted.text
    return client.get(f"/assistant/runs/{accepted.json()['id']}", headers=headers()).json()


def _client(tmp_path: Path, **kwargs):
    services = make_services(tmp_path, **kwargs)
    return make_client(tmp_path, services=services)


def test_published_answer_reports_its_route(tmp_path):
    client = _client(tmp_path)
    result = _run(client, _session(client)["id"], "What can you do?")["result"]

    assert result["route"] == "published"
    assert result["web"] == {"requested": False, "status": "off", "reason": None, "hint": None}
    assert all(citation["source_type"] != "general_web" for citation in result["citations"])


def test_document_answer_reports_document_route(tmp_path):
    client = _client(tmp_path)
    text = "This guarantee is governed by URDG 758 and payable on first written demand."
    snapshot = register_snapshot(client, text=text)
    session = _session(
        client,
        {
            "workspace_id": WORKSPACE,
            "locale": "en",
            "document_id": "doc-1",
            "snapshot_id": snapshot["id"],
        },
    )
    start = text.index("URDG 758")
    selection = {
        "node_id": "block_0",
        "start_offset": start,
        "end_offset": start + len("URDG 758"),
        "selected_text": "URDG 758",
    }
    result = _run(
        client, session["id"], "What does this passage mean?", selection=selection
    )["result"]

    assert result["route"] == "document"


def test_handoff_answer_reports_handoff_route(tmp_path):
    client = _client(tmp_path)
    result = _run(client, _session(client)["id"], "帮我改写这段条款", web=True)["result"]

    assert result["route"] == "handoff"
    assert result["web"]["requested"] is True
    assert result["web"]["status"] == "skipped"
    assert result["web"]["hint"]


def test_requested_web_without_provider_explains_itself(tmp_path):
    client = _client(tmp_path)
    result = _run(client, _session(client)["id"], "What can you do?", web=True)["result"]

    assert result["route"] == "published"
    assert result["web"]["requested"] is True
    assert result["web"]["status"] == "skipped"
    assert result["web"]["reason"] == "web_unavailable"
    assert "no web provider" in result["web"]["hint"].lower()


def test_general_web_answer_reports_general_route_and_citations(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Markets published an update today.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://iccwbo.org/news/1",
                                        "title": "Today's trade update",
                                        "start_index": 0,
                                        "end_index": 9,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        )

    gateway = DoubaoGateway(
        api_key="k",
        base_url="https://ark.example/api/v3",
        model="seed-1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        timeout=1.0,
        search_timeout=1.0,
    )
    services = make_services(
        tmp_path,
        gateway=gateway,
        egress=EgressPolicy(version="t", allowed_domains=["iccwbo.org"]),
        settings=AssistantSettings(
            model="doubao:seed-1",
            api_key="k",
            approved_processor=True,
            general_web=True,
        ),
    )
    client = make_client(tmp_path, services=services)
    result = _run(
        client, _session(client)["id"], "What happened in the market today?", web=True
    )["result"]

    assert result["route"] == "general_web"
    assert result["web"]["status"] == "ok"
    assert result["citations"]
    assert all(citation["source_type"] == "general_web" for citation in result["citations"])