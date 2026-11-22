"""Automation access boundary over HTTP: view / configure / dispatch / audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.documents.bootstrap import build_host_services
from tests.assistant_helpers import make_services


@pytest.fixture
def host(tmp_path):
    return build_host_services(db_path=tmp_path / "host.db", mode="test")


@pytest.fixture
def client(tmp_path, host):
    app = create_app(
        llm=None,
        runs_dir=tmp_path / "runs",
        assistant_services=make_services(tmp_path, seed=False),
        host_services=host,
    )
    with TestClient(app) as test_client:
        yield test_client


def _h(*capabilities: str) -> dict[str, str]:
    return {"X-Demo-User": "usr_ops", "X-Demo-Capabilities": ",".join(capabilities)}


TEMPLATE = {"name": "Demand guarantee", "text": "Amount: {{amount}}", "source_kind": "imported"}


def test_a_plain_member_cannot_touch_automation(client: TestClient):
    headers = _h("read", "edit")

    assert client.get("/automation/templates", headers=headers).status_code == 403
    assert client.post("/automation/templates", json=TEMPLATE, headers=headers).status_code == 403
    assert client.get("/automation/jobs", headers=headers).status_code == 403
    assert client.get("/automation/settings", headers=headers).status_code == 403
    assert (
        client.post(
            "/automation/dispatches",
            json={"template_id": "tpl_x", "connector_id": "con_x"},
            headers=headers,
        ).status_code
        == 403
    )


def test_a_viewer_can_read_but_not_configure_or_send(client: TestClient):
    headers = _h("read", "automation_view", "automation_audit")

    assert client.get("/automation/templates", headers=headers).status_code == 200
    assert client.get("/automation/dispatches", headers=headers).status_code == 200
    assert client.get("/automation/jobs", headers=headers).status_code == 200
    assert client.get("/automation/settings", headers=headers).status_code == 200
    assert client.post("/automation/templates", json=TEMPLATE, headers=headers).status_code == 403
    assert (
        client.post("/automation/jobs/job_missing/retry", headers=headers).status_code == 403
    )
    assert (
        client.post(
            "/automation/dispatches",
            json={"template_id": "tpl_x", "connector_id": "con_x"},
            headers=headers,
        ).status_code
        == 403
    )


def test_bank_operations_can_configure_and_dispatch(client: TestClient):
    headers = _h(
        "read", "automation_view", "automation_configure", "automation_dispatch", "automation_audit"
    )

    created = client.post("/automation/templates", json=TEMPLATE, headers=headers)
    assert created.status_code == 201, created.text

    # The capability gate passes; the missing connector is what stops the call (404, not 403).
    sent = client.post(
        "/automation/dispatches",
        json={"template_id": created.json()["template_id"], "connector_id": "con_missing"},
        headers=headers,
    )
    assert sent.status_code == 404