"""HTTP contract for `/legal/*`: 202 + report, project error body, honest statute failure."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.errors import ApiFailure, error_body
from app.api.legal import router

app = FastAPI()
app.include_router(router)


@app.exception_handler(ApiFailure)
async def _api_failure(request: Request, exc: ApiFailure) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=exc.status, content=error_body(exc.code, exc.message, exc.detail)
    )


client = TestClient(app)

SUBMIT = {
    "workspace_id": "ws_demo",
    "document_id": "doc_demo",
    "snapshot_id": "snap_01",
    "facts_version_id": "facts_01",
    "modes": ["deterministic"],
    "facts": {},
}


def test_submit_returns_202_with_a_location_and_a_report():
    response = client.post("/legal/reviews", json=SUBMIT)

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["report_id"]
    assert response.headers["location"] == f"/legal/reports/{run['report_id']}"
    assert response.headers["cache-control"] == "no-store"

    report = client.get(f"/legal/reports/{run['report_id']}")
    assert report.status_code == 200
    body = report.json()
    assert body["outcome"] == "findings_present"
    finding = body["findings"][0]
    assert body["coverage"][0]["finding_ids"] == [finding["finding_id"]]
    assert report.headers["cache-control"] == "no-store"


def test_an_unknown_report_uses_the_project_error_contract():
    response = client.get("/legal/reports/rep_missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "resource_unavailable",
        "message": "legal report not found",
    }


def test_legal_mode_without_a_statute_layer_is_unable_to_assess():
    response = client.post(
        "/legal/reviews",
        json={**SUBMIT, "modes": ["legal"], "question": "银行保函有哪些法律要求？"},
    )
    assert response.status_code == 202

    report = client.get(f"/legal/reports/{response.json()['report_id']}").json()
    assert report["outcome"] == "unable_to_assess"
    assert report["findings"] == []
    assert report["coverage"][0]["status"] == "failed"
    assert report["coverage"][0]["reason_codes"] == ["statute_unavailable"]