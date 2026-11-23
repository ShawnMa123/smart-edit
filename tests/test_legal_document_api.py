"""HTTP contract for a document scan: 202 + pollable run + report with coverage and gate."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.errors import ApiFailure, error_body
from app.api.legal import router
from app.documents.projection import plain_text_document
from app.legal_review.service import LegalService
from app.legal_review.store import LegalStore

TEXT = """DEMAND GUARANTEE
Applicant: Atlas Trading Ltd
Beneficiary: Meridian Exports Pte Ltd
Amount: USD 250,000.00
Issue date: 2026-01-10
Expiry date: 2027-06-30
Governing rules: URDG 758
Jurisdiction: Singapore
Claim documents: demand and statement
The bank will pay against the documents presented.
"""


class FakeDocuments:
    def __init__(self, revision: int = 3) -> None:
        self.revision = revision

    def document_view(self, principal, document_id):
        return {
            "document_id": document_id,
            "draft_id": "draft_1",
            "title": "Demand Guarantee",
            "revision": self.revision,
            "content_sha256": "sha-3",
            "text": TEXT,
            "content": plain_text_document(TEXT),
        }


def _client(documents: FakeDocuments) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(ApiFailure)
    async def _api_failure(request: Request, exc: ApiFailure) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=error_body(exc.code, exc.message, exc.detail)
        )

    app.state.legal = LegalService(store=LegalStore(":memory:"), documents=documents)
    return TestClient(app)


def _poll(client: TestClient, run_id: str) -> dict:
    for _ in range(100):
        run = client.get(f"/legal/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.02)
    raise AssertionError("the scan never finished")


def test_document_scope_returns_a_pollable_run_and_a_report():
    client = _client(FakeDocuments())

    response = client.post(
        "/legal/reviews",
        json={
            "workspace_id": "ws_demo_01",
            "document_id": "demo-document",
            "scope": "document",
            "modes": ["deterministic"],
            "expected_revision": 3,
            "applicable_on": "2026-11-20",
        },
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["run_id"]
    assert accepted["report_id"]
    assert response.headers["location"] == f"/legal/reports/{accepted['report_id']}"

    run = _poll(client, accepted["run_id"])
    assert run["status"] == "succeeded"
    assert run["stage"] == "done"
    assert run["progress"]["stage"] == "done"

    report = client.get(f"/legal/reports/{accepted['report_id']}").json()
    assert report["snapshot"]["revision"] == 3
    assert report["snapshot"]["document_id"] == "demo-document"
    assert report["coverage_summary"]["planned"] == len(report["coverage"])
    assert report["gate"]["policy"] == "legal-scan/1"
    assert report["retrieval"]["queries"] == 0  # the legal leg was not requested
    assert report["outcome"] in ("no_findings", "needs_input", "unable_to_assess")


def test_a_stale_revision_fails_the_polled_run_with_a_code():
    client = _client(FakeDocuments(revision=9))

    accepted = client.post(
        "/legal/reviews",
        json={
            "workspace_id": "ws_demo_01",
            "document_id": "demo-document",
            "scope": "document",
            "modes": ["deterministic"],
            "expected_revision": 3,
        },
    ).json()

    run = _poll(client, accepted["run_id"])
    assert run["status"] == "failed"
    assert run["error"] == "stale_snapshot"
    assert client.get(f"/legal/reports/{accepted['report_id']}").status_code == 404


def test_an_unknown_run_uses_the_project_error_contract():
    client = _client(FakeDocuments())

    response = client.get("/legal/runs/lr_missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "resource_unavailable",
        "message": "legal run not found",
    }