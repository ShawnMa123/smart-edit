"""Runs API, delivery aggregation and the manual fallback (automation-auto-dispatch §5)."""

from __future__ import annotations

import pytest

from app.automation.jobs import AutomationJobService
from app.automation.worker import AutomationWorker
from app.documents.errors import HostError, HostNotFound
from tests.automation_helpers import (
    FakeActivity,
    FakeAuthorizer,
    approve,
    build,
    connector,
    principal,
    rule,
)


class _Response:
    def __init__(self, status_code: int = 200, text: str = '{"ok": true}') -> None:
        self.status_code = status_code
        self.text = text


def fake_http(monkeypatch, statuses: int | dict[str, int] = 200) -> None:
    """`statuses` may map a URL fragment (connector path) to its status."""

    def request(*args, **kwargs):
        url = str(kwargs.get("url") or (args[1] if len(args) > 1 else ""))
        if isinstance(statuses, dict):
            for fragment, status in statuses.items():
                if fragment in url:
                    return _Response(status)
            return _Response(200)
        return _Response(statuses)

    monkeypatch.setattr("app.automation.registry.httpx.request", request)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fixture = build(tmp_path, monkeypatch)
    activity = FakeActivity()
    authorizer = FakeAuthorizer()
    jobs = AutomationJobService(
        fixture["host"].store,
        fixture["registry"],
        activity=activity,
        authorizer=authorizer,
    )
    worker = AutomationWorker(
        fixture["host"].store,
        fixture["registry"],
        auto_send=True,
        activity=activity,
        authorizer=authorizer,
    )
    return {**fixture, "jobs": jobs, "worker": worker, "activity": activity}


def _approve(setup) -> str:
    return approve(
        setup["host"], setup["document"]["document_id"], "Amount: USD 750,000.00"
    )


def _rule_for(setup, *, name: str, path: str, mode: str = "auto_send", required: bool = True):
    connection = connector(setup["registry"], setup["principal"], name=name, path=path)
    return rule(
        setup["rules"],
        setup["principal"],
        setup["template"],
        connection,
        mode=mode,
        required=required,
    )


def _delivery(setup):
    return setup["jobs"].document_delivery(
        setup["principal"], setup["document"]["document_id"]
    )


# --- delivery aggregation ---------------------------------------------------------------------


def test_a_failed_required_downstream_makes_the_document_needs_attention(setup, monkeypatch):
    fake_http(monkeypatch, {"/erp": 200, "/core": 200, "/legacy": 409})
    _rule_for(setup, name="ERP", path="/erp")
    _rule_for(setup, name="Core", path="/core")
    _rule_for(setup, name="Legacy", path="/legacy")
    _approve(setup)

    setup["worker"].run_once()

    delivery = _delivery(setup)
    assert delivery.status == "needs_attention"
    assert len(delivery.rows) == 3
    assert {row.status for row in delivery.rows} == {"sent", "needs_attention"}
    failed = [row for row in delivery.rows if row.status == "needs_attention"][0]
    assert failed.error_code and failed.connector_name == "Legacy"


def test_an_optional_failure_still_counts_as_sent(setup, monkeypatch):
    fake_http(monkeypatch, {"/erp": 200, "/core": 409})
    _rule_for(setup, name="ERP", path="/erp")
    _rule_for(setup, name="Core", path="/core", required=False)
    _approve(setup)

    setup["worker"].run_once()

    delivery = _delivery(setup)
    assert delivery.status == "sent"
    optional = [row for row in delivery.rows if not row.required][0]
    assert optional.status == "needs_attention"
    assert optional.error_code


def test_a_document_with_a_queued_required_downstream_is_partial(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp")
    _rule_for(setup, name="Core", path="/core")
    _approve(setup)
    setup["worker"].run_once()

    # Simulate a worker restart between two fan-out jobs: one sent, one waiting.
    sent_job = [
        job
        for job in setup["host"].store.automation_jobs("ws_demo")
        if job["status"] == "sent"
    ][0]
    setup["host"].store.update_automation_job(sent_job["job_id"], status="queued")

    assert _delivery(setup).status == "partial"


def test_no_rule_reports_not_configured_with_the_skip_reason(setup):
    _approve(setup)

    setup["worker"].run_once()

    delivery = _delivery(setup)
    assert delivery.status == "not_configured"
    assert delivery.skipped_reason == "no_rule"
    assert delivery.rows == []


def test_an_unbound_document_reports_no_binding(setup):
    owner = setup["principal"]
    from app.documents.schemas import DocumentCreate

    other = setup["host"].documents.create_document(
        owner, DocumentCreate(title="Unbound", text="Amount: 1"), "req_unbound"
    )
    approve(setup["host"], other["document_id"], "Amount: 1")

    setup["worker"].run_once()

    delivery = setup["jobs"].document_delivery(owner, other["document_id"])
    assert delivery.status == "not_configured"
    assert delivery.skipped_reason == "no_binding"


def test_a_shadow_only_run_is_shadowed(setup):
    _rule_for(setup, name="ERP", path="/erp", mode="shadow")
    _approve(setup)

    setup["worker"].run_once()

    assert _delivery(setup).status == "shadowed"


# --- manual fallback --------------------------------------------------------------------------


def test_release_queues_a_needs_review_job_and_the_worker_sends_it(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp", mode="needs_review")
    _approve(setup)
    setup["worker"].run_once()

    job = setup["host"].store.automation_jobs("ws_demo")[0]
    assert job["status"] == "needs_review"
    assert setup["host"].store.all("SELECT * FROM automation_dispatches") == []

    released = setup["jobs"].release(setup["principal"], job["job_id"])
    assert released.status == "queued"

    setup["worker"].run_once()
    assert setup["host"].store.automation_job(job["job_id"])["status"] == "sent"
    assert _delivery(setup).status == "sent"


def test_release_rejects_a_job_that_is_not_waiting_for_review(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp")
    _approve(setup)
    setup["worker"].run_once()
    job = setup["host"].store.automation_jobs("ws_demo")[0]

    with pytest.raises(HostError) as failure:
        setup["jobs"].release(setup["principal"], job["job_id"])
    assert failure.value.status == 409
    assert failure.value.code == "job_not_releasable"


def test_retry_requeues_a_failed_job_and_keeps_the_attempt_count(setup, monkeypatch):
    fake_http(monkeypatch, 409)
    _rule_for(setup, name="ERP", path="/erp")
    _approve(setup)
    setup["worker"].run_once()
    job = setup["host"].store.automation_jobs("ws_demo")[0]
    assert job["status"] == "needs_attention"
    assert job["attempts"] == 1

    retried = setup["jobs"].retry(setup["principal"], job["job_id"])

    assert retried.status == "queued"
    assert retried.error_code is None
    assert retried.attempts == 1  # the next attempt uses a new idempotency suffix


def test_retry_rejects_a_sent_job(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp")
    _approve(setup)
    setup["worker"].run_once()
    job = setup["host"].store.automation_jobs("ws_demo")[0]

    with pytest.raises(HostError) as failure:
        setup["jobs"].retry(setup["principal"], job["job_id"])
    assert failure.value.status == 409
    assert failure.value.code == "job_not_retryable"


def test_cancel_stops_a_queued_job_but_not_a_sent_one(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp", mode="shadow")
    _approve(setup)
    # The approval event is consumed (job queued) but no job has run yet.
    setup["worker"].consume_approvals()
    job = setup["host"].store.automation_jobs("ws_demo")[0]
    assert job["status"] == "queued"

    cancelled = setup["jobs"].cancel(setup["principal"], job["job_id"])
    assert cancelled.status == "cancelled"

    with pytest.raises(HostError) as failure:
        setup["jobs"].cancel(setup["principal"], job["job_id"])
    assert failure.value.code == "job_not_cancellable"

    # A cancelled job can be retried back into the queue.
    assert setup["jobs"].retry(setup["principal"], job["job_id"]).status == "queued"


# --- reads, scope and settings ----------------------------------------------------------------


def test_list_and_detail_expose_the_timeline_and_required_flag(setup):
    _rule_for(setup, name="ERP", path="/erp", mode="shadow", required=False)
    _approve(setup)
    setup["worker"].run_once()
    job_id = setup["host"].store.automation_jobs("ws_demo")[0]["job_id"]

    page = setup["jobs"].list(
        setup["principal"], document_id=setup["document"]["document_id"]
    )
    assert [item.job_id for item in page.items] == [job_id]
    assert page.items[0].required is False
    assert page.items[0].connector_name == "ERP"

    detail = setup["jobs"].detail(setup["principal"], job_id)
    assert [event.to_status for event in detail.events] == ["queued", "shadowed"]

    with pytest.raises(HostNotFound):
        setup["jobs"].detail(setup["principal"], "job_missing")


def test_a_viewer_can_read_but_not_act(setup):
    _rule_for(setup, name="ERP", path="/erp", mode="shadow")
    _approve(setup)
    setup["worker"].run_once()
    job = setup["host"].store.automation_jobs("ws_demo")[0]
    viewer = principal(
        user_id="usr_audit",
        roles=("compliance",),
        capabilities=("read", "automation_view", "automation_audit"),
    )

    assert setup["jobs"].list(viewer).items[0].job_id == job["job_id"]
    with pytest.raises(HostError) as failure:
        setup["jobs"].cancel(viewer, job["job_id"])
    assert failure.value.status == 403


def test_the_kill_switch_degrades_auto_send_to_shadow(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp")
    _approve(setup)
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_AUTO_SEND", "0")
    degraded = AutomationWorker(setup["host"].store, setup["registry"], auto_send=False)

    degraded.run_once()

    job = setup["host"].store.automation_jobs("ws_demo")[0]
    assert job["status"] == "shadowed"
    assert setup["host"].store.all("SELECT * FROM automation_dispatches") == []
    assert setup["jobs"].settings(setup["principal"]).auto_send_enabled is False
    delivery = _delivery(setup)
    assert delivery.status == "shadowed"
    assert delivery.auto_send_enabled is False


def test_delivery_status_changes_are_written_to_activity(setup, monkeypatch):
    fake_http(monkeypatch)
    _rule_for(setup, name="ERP", path="/erp")
    _approve(setup)

    setup["worker"].run_once()

    events = [event for event in setup["activity"].events if event["kind"] == "automation"]
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "delivery.sent"
    assert event["actor_user_id"] == "system:automation"
    assert event["resource_type"] == "document"
    assert event["detail"]["document_id"] == setup["document"]["document_id"]
    assert event["detail"]["connector_id"]
    assert event["detail"]["status"] == "sent"