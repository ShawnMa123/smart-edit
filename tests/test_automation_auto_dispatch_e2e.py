"""End-to-end automatic dispatch: real echo downstream, real approval, shadow → auto_send.

This is the §6.1 drill: Bank Ops rules start in `shadow`, the final approval only produces records,
then an explicit tier upgrade makes the next final approval reach every downstream for real.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.automation.jobs import AutomationJobService
from app.automation.registry_schemas import ConnectorCreate
from app.automation.rule_schemas import RuleCreate
from app.automation.rules import AutomationRuleService
from app.automation.worker import AutomationWorker
from app.documents.schemas import DocumentCreate
from tests.automation_helpers import FakeActivity, FakeAuthorizer, approve, build


class _EchoHandler(BaseHTTPRequestHandler):
    records: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.records.append({"path": self.path, "payload": payload})
        body = json.dumps({"accepted": True, "path": self.path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep pytest output clean
        return


@pytest.fixture
def echo():
    _EchoHandler.records = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, _EchoHandler.records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _connector_at(registry, owner, name: str, path: str, port: int):
    return registry.create_connector(
        owner,
        ConnectorCreate(name=name, base_url=f"http://127.0.0.1:{port}", path=path),
    )


def test_final_approval_shadows_first_then_reaches_every_downstream_once(
    tmp_path, monkeypatch, echo
):
    server, records = echo
    fixture = build(tmp_path, monkeypatch)
    # Point both connectors at the ephemeral echo port instead of the shared demo port.
    port = server.server_address[1]
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")

    host = fixture["host"]
    registry = fixture["registry"]
    rules = fixture["rules"]
    owner = fixture["principal"]
    template = fixture["template"]
    document = fixture["document"]

    erp = _connector_at(registry, owner, "ERP", "/erp", port)
    core = _connector_at(registry, owner, "Core", "/core", port)
    shadow = rules.create(
        owner,
        RuleCreate(name="ERP shadow", template_name=template.name, connector_id=erp.connector_id),
    )
    rules.create(
        owner,
        RuleCreate(name="Core shadow", template_name=template.name, connector_id=core.connector_id),
    )

    activity = FakeActivity()
    jobs = AutomationJobService(
        host.store, registry, activity=activity, authorizer=FakeAuthorizer()
    )
    worker = AutomationWorker(
        host.store, registry, auto_send=True, activity=activity, authorizer=FakeAuthorizer()
    )

    # 1. First final approval: the rules are still in shadow, nothing leaves the process.
    approve(host, document["document_id"], "Amount: USD 750,000.00")
    worker.run_once()
    assert records == []
    assert host.store.all("SELECT * FROM automation_dispatches") == []
    assert jobs.document_delivery(owner, document["document_id"]).status == "shadowed"

    # 2. Bank Ops raises both tiers explicitly (audited), then the next final approval sends.
    rules.set_mode(owner, shadow.rule_id, "auto_send")
    core_rule = [item for item in rules.list(owner) if item.name == "Core shadow"][0]
    rules.set_mode(owner, core_rule.rule_id, "auto_send")

    submission_id = approve(host, document["document_id"], "Amount: USD 750,000.00")
    worker.run_once()

    delivery = jobs.document_delivery(owner, document["document_id"])
    assert delivery.status == "sent"
    assert len(delivery.rows) == 2
    assert {row.status for row in delivery.rows} == {"sent"}
    assert {record["path"] for record in records} == {"/erp", "/core"}
    assert len(records) == 2  # one call per downstream, no duplicate for the replayed document
    assert all(record["payload"]["values"]["amount"] == "USD 750,000.00" for record in records)

    receipts = host.store.all("SELECT * FROM automation_dispatches")
    assert len(receipts) == 2
    for receipt in receipts:
        assert receipt["job_id"]
        assert receipt["rule_id"]
        assert receipt["trigger"] == "final_approval"
        assert receipt["submission_id"] == submission_id
        assert receipt["created_by"] == "system:automation"

    delivered = [event for event in activity.events if event["action"] == "delivery.sent"]
    assert delivered and delivered[-1]["kind"] == "automation", [
        (event["action"], event["detail"].get("status")) for event in activity.events
    ]


def test_rollback_drill_stopped_worker_and_kill_switch_never_send(tmp_path, monkeypatch, echo):
    """§6.3: stopping the worker leaves approvals inert; the kill switch turns a real send into shadow."""
    server, records = echo
    fixture = build(tmp_path, monkeypatch)
    port = server.server_address[1]
    host = fixture["host"]
    registry = fixture["registry"]
    rules = fixture["rules"]
    owner = fixture["principal"]
    template = fixture["template"]
    document = fixture["document"]
    connection = _connector_at(registry, owner, "ERP", "/erp", port)
    rules.create(
        owner,
        RuleCreate(
            name="ERP auto",
            template_name=template.name,
            connector_id=connection.connector_id,
            mode="auto_send",
        ),
    )

    # 1. Worker stopped: the final approval is written, but nothing is planned or sent.
    approve(host, document["document_id"], "Amount: USD 750,000.00")
    assert records == []
    assert host.store.automation_jobs("ws_demo") == []
    assert host.store.all("SELECT * FROM automation_dispatches") == []

    # 2. Kill switch on, worker running: the same rule produces a shadow record, not a call.
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_AUTO_SEND", "0")
    worker = AutomationWorker(
        host.store,
        registry,
        auto_send=False,
        activity=FakeActivity(),
        authorizer=FakeAuthorizer(),
    )
    worker.run_once()

    jobs = host.store.automation_jobs("ws_demo")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "shadowed"
    assert records == []
    assert host.store.all("SELECT * FROM automation_dispatches") == []
    assert AutomationJobService(host.store, registry).settings(owner).auto_send_enabled is False