"""Automatic dispatch worker: final approval → jobs → shadow / review / send."""

from __future__ import annotations

import json

import pytest

from app.automation.registry import AutomationRegistry
from app.automation.registry_schemas import ConnectorCreate, TemplateCreate, TemplateVariablesUpdate
from app.automation.rule_schemas import RuleCreate
from app.automation.rules import AutomationRuleService
from app.automation.worker import AutomationWorker, retryable
from app.documents.bootstrap import build_host_services
from app.documents.schemas import DocumentCreate
from app.documents.store import new_id, now_iso
from app.shared.ports import Principal


def _principal(**overrides) -> Principal:
    values = {
        "user_id": "usr_ops",
        "workspace_id": "ws_demo",
        "roles": ("bank_ops",),
        "capabilities": (
            "read",
            "edit",
            "automation_view",
            "automation_configure",
            "automation_dispatch",
            "automation_audit",
        ),
    }
    values.update(overrides)
    return Principal(**values)


def _approve(host, document_id: str, text: str) -> str:
    """Create a submission in `pending_second`, then let the second approver approve it."""
    submission_id = new_id("sub")
    request_id = new_id("apr")
    stamp = now_iso()
    with host.store.transaction() as conn:
        conn.execute(
            "INSERT INTO document_submissions (submission_id, document_id, draft_id, workspace_id,"
            " department_id, submitted_by, revision, content_sha256, content_json, text,"
            " variables_json, variables_version, status, request_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                submission_id,
                document_id,
                "draft_x",
                "ws_demo",
                None,
                "usr_applicant",
                1,
                "sha",
                json.dumps({}, ensure_ascii=False),
                text,
                "{}",
                1,
                "pending_second",
                request_id,
                stamp,
            ),
        )
        conn.execute(
            "INSERT INTO approval_requests (request_id, submission_id, document_id, workspace_id,"
            " department_id, submitted_by, status, current_stage, revision, created_at,"
            " updated_at, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                request_id,
                submission_id,
                document_id,
                "ws_demo",
                None,
                "usr_applicant",
                "pending_second",
                "second",
                1,
                stamp,
                stamp,
                None,
            ),
        )
    host.store.decide_approval(
        request_id=request_id,
        stage="second",
        decision="approve",
        actor_user_id="usr_second",
        comment=None,
        expected_revision=1,
    )
    return submission_id


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    rules = AutomationRuleService(host.store, registry)
    worker = AutomationWorker(host.store, registry, auto_send=True)
    principal = _principal()

    template = registry.create_template(
        principal, TemplateCreate(name="Demand guarantee", text="Amount: {{amount}}")
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal,
        template.template_id,
        TemplateVariablesUpdate(variables=suggestion.variables),
    )
    document = host.documents.create_document(
        principal, DocumentCreate(title="G", text="Amount: USD 750,000.00"), "req_doc"
    )
    host.store.bind_document_template(
        document_id=document["document_id"],
        workspace_id="ws_demo",
        template_id=template.template_id,
        template_name=template.name,
        actor="usr_ops",
    )
    return host, registry, rules, worker, principal, template, document


def _connector(registry, principal, name="ERP"):
    return registry.create_connector(
        principal, ConnectorCreate(name=name, base_url="http://127.0.0.1:18080")
    )


def _rule(rules, principal, template, connector, *, mode="shadow"):
    return rules.create(
        principal,
        RuleCreate(
            name=f"{mode} rule",
            template_name=template.name,
            connector_id=connector.connector_id,
            mode=mode,
        ),
    )


class _Response:
    def __init__(self, status_code: int = 200, text: str = '{"ok": true}') -> None:
        self.status_code = status_code
        self.text = text


def _fake_http(monkeypatch, status_code: int = 200) -> None:
    monkeypatch.setattr(
        "app.automation.registry.httpx.request",
        lambda *args, **kwargs: _Response(status_code),
    )


def test_final_approval_plans_a_shadow_job_without_a_receipt(setup):
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal), mode="shadow")
    _approve(host, document["document_id"], "Amount: USD 750,000.00")

    result = worker.run_once()

    assert result == {"events": 1, "jobs": 1}
    jobs = host.store.automation_jobs("ws_demo")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "shadowed"
    assert json.loads(jobs[0]["request_json"])["body"]
    assert host.store.all("SELECT * FROM automation_dispatches") == []


def test_unbound_document_is_skipped_with_no_binding(setup):
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal))
    other = host.documents.create_document(
        principal, DocumentCreate(title="Unbound", text="Amount: 1"), "req_unbound"
    )
    _approve(host, other["document_id"], "Amount: 1")

    worker.run_once()

    jobs = host.store.automation_jobs("ws_demo")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "skipped"
    assert jobs[0]["error_code"] == "no_binding"
    assert host.store.all("SELECT * FROM automation_dispatches") == []


def test_fan_out_to_two_downstreams_dedupes_the_same_connector(setup, monkeypatch):
    _fake_http(monkeypatch)
    host, registry, rules, worker, principal, template, document = setup
    erp = _connector(registry, principal, "ERP")
    core = _connector(registry, principal, "Core")
    _rule(rules, principal, template, erp, mode="auto_send")
    _rule(rules, principal, template, core, mode="auto_send")
    _rule(rules, principal, template, erp, mode="auto_send")  # duplicate downstream
    _approve(host, document["document_id"], "Amount: USD 750,000.00")

    worker.run_once()

    jobs = host.store.automation_jobs("ws_demo")
    assert len(jobs) == 2
    assert {job["connector_id"] for job in jobs} == {erp.connector_id, core.connector_id}
    assert {job["status"] for job in jobs} == {"sent"}


def test_auto_send_links_the_receipt_to_job_rule_and_submission(setup, monkeypatch):
    _fake_http(monkeypatch)
    host, registry, rules, worker, principal, template, document = setup
    connector = _connector(registry, principal)
    rule = _rule(rules, principal, template, connector, mode="auto_send")
    submission_id = _approve(host, document["document_id"], "Amount: USD 750,000.00")

    worker.run_once()

    job = host.store.automation_jobs("ws_demo")[0]
    assert job["status"] == "sent"
    receipt = host.store.one(
        "SELECT * FROM automation_dispatches WHERE dispatch_id = ?", (job["receipt_id"],)
    )
    assert receipt is not None
    assert receipt["job_id"] == job["job_id"]
    assert receipt["rule_id"] == rule.rule_id
    assert receipt["submission_id"] == submission_id
    assert receipt["trigger"] == "final_approval"
    assert receipt["created_by"] == "system:automation"
    assert receipt["template_id"] == template.template_id


def test_needs_review_waits_for_a_release(setup, monkeypatch):
    _fake_http(monkeypatch)
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal), mode="needs_review")
    _approve(host, document["document_id"], "Amount: USD 750,000.00")

    worker.run_once()

    job = host.store.automation_jobs("ws_demo")[0]
    assert job["status"] == "needs_review"
    assert host.store.all("SELECT * FROM automation_dispatches") == []


def test_5xx_retries_then_needs_attention(setup, monkeypatch):
    _fake_http(monkeypatch, status_code=500)
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal), mode="auto_send")
    _approve(host, document["document_id"], "Amount: USD 750,000.00")

    worker.run_once()
    job = host.store.automation_jobs("ws_demo")[0]
    assert job["status"] == "queued"
    assert job["attempts"] == 1
    assert job["next_attempt_at"]

    for _ in range(2):
        host.store.update_automation_job(job["job_id"], next_attempt_at=None)
        worker.run_once()

    job = host.store.automation_job(job["job_id"])
    assert job["status"] == "needs_attention"
    assert job["attempts"] == 3


def test_4xx_is_not_retried(setup, monkeypatch):
    _fake_http(monkeypatch, status_code=409)
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal), mode="auto_send")
    _approve(host, document["document_id"], "Amount: USD 750,000.00")

    worker.run_once()

    job = host.store.automation_jobs("ws_demo")[0]
    assert job["status"] == "needs_attention"
    assert job["attempts"] == 1


def test_retryable_classification():
    assert retryable("http_500", 500) is True
    assert retryable("timeout", None) is True
    assert retryable("transport_error:ConnectError", None) is True
    assert retryable("missing_required_body", 409) is False
    assert retryable("host_not_allowed", 403) is False


def test_job_creation_is_idempotent_per_rule_and_submission(setup):
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal))
    submission_id = _approve(host, document["document_id"], "Amount: USD 750,000.00")

    first = worker.consume_approvals()
    assert first == 1
    job = host.store.automation_jobs("ws_demo")[0]
    # A replayed approval event must not create a second job for the same (rule, submission).
    same = host.store.create_automation_job(
        job_id="job_other",
        workspace_id="ws_demo",
        rule_id=job["rule_id"],
        document_id=job["document_id"],
        submission_id=submission_id,
        template_id=job["template_id"],
        connector_id=job["connector_id"],
        status="queued",
        mode="shadow",
        idempotency_key=job["idempotency_key"],
    )
    assert same["job_id"] == job["job_id"]
    assert len(host.store.automation_jobs("ws_demo")) == 1


def test_the_body_comes_from_the_approved_snapshot_not_the_live_draft(setup, monkeypatch):
    _fake_http(monkeypatch)
    host, registry, rules, worker, principal, template, document = setup
    _rule(rules, principal, template, _connector(registry, principal), mode="auto_send")
    _approve(host, document["document_id"], "Amount: USD 750,000.00")

    # Someone keeps editing the draft after approval; the automatic body must not change.
    with host.store.transaction() as conn:
        conn.execute(
            "UPDATE document_drafts SET text = ? WHERE document_id = ?",
            ("Amount: USD 1.00", document["document_id"]),
        )

    worker.run_once()

    job = host.store.automation_jobs("ws_demo")[0]
    receipt = host.store.one(
        "SELECT * FROM automation_dispatches WHERE dispatch_id = ?", (job["receipt_id"],)
    )
    payload = json.loads(receipt["request_json"])
    assert payload["values"]["amount"] == "USD 750,000.00"
    assert json.loads(receipt["request_json"])["dispatch"]["dispatch_id"]


def test_schema_v10_migrates_job_tables_and_receipt_links(tmp_path):
    import sqlite3

    from app.documents.store import SCHEMA_VERSION

    db_path = tmp_path / "host.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES ('schema_version','10');"
        "CREATE TABLE automation_dispatches (dispatch_id TEXT PRIMARY KEY,"
        " workspace_id TEXT NOT NULL, template_id TEXT, connector_id TEXT NOT NULL,"
        " document_id TEXT, status TEXT NOT NULL, status_code INTEGER, latency_ms INTEGER,"
        " request_json TEXT NOT NULL, response_json TEXT, error_code TEXT,"
        " idempotency_key TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL);"
    )
    conn.commit()
    conn.close()

    from app.documents.store import HostStore

    store = HostStore(db_path)
    assert store.schema_version() == SCHEMA_VERSION
    dispatch_columns = {
        row["name"] for row in store.all("PRAGMA table_info(automation_dispatches)")
    }
    assert {"job_id", "rule_id", "trigger", "submission_id"} <= dispatch_columns
    job_columns = {row["name"] for row in store.all("PRAGMA table_info(automation_jobs)")}
    assert {"job_id", "status", "idempotency_key", "receipt_id", "required"} <= job_columns
    event_columns = {
        row["name"] for row in store.all("PRAGMA table_info(automation_job_events)")
    }
    assert {"job_id", "to_status"} <= event_columns