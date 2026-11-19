"""Deployment defaults for the web fallback (`knowledge-simple-ask`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.assistant.ports import Principal
from app.assistant.schemas import RunCreate, SessionCreate
from app.assistant.settings import WEB_DEFAULT_ENV, AssistantSettings
from app.assistant.statute import StatuteOutcome
from tests.assistant_helpers import WORKSPACE, headers, make_client, make_service, make_services

QUESTION = "What are the rules on the origin of goods?"
PRINCIPAL = Principal("user_scope", WORKSPACE)


# --- settings -------------------------------------------------------------------------------


def test_the_web_fallback_defaults_to_on():
    assert AssistantSettings.from_env({}).web_default is True


@pytest.mark.parametrize("value", ["off", "false", "0", "no"])
def test_the_default_can_be_switched_off(value):
    assert AssistantSettings.from_env({WEB_DEFAULT_ENV: value}).web_default is False


@pytest.mark.parametrize("value", ["on", "true", "1", "yes"])
def test_the_default_can_be_switched_on(value):
    assert AssistantSettings.from_env({WEB_DEFAULT_ENV: value}).web_default is True


def test_an_invalid_default_fails_loudly():
    with pytest.raises(ValueError, match=WEB_DEFAULT_ENV):
        AssistantSettings.from_env({WEB_DEFAULT_ENV: "maybe"})


# --- capabilities ---------------------------------------------------------------------------


def capabilities(tmp_path: Path, *, settings: AssistantSettings | None = None) -> dict:
    services = make_services(tmp_path, settings=settings)
    with make_client(tmp_path, services=services) as client:
        response = client.get("/assistant/capabilities", headers=headers())
    assert response.status_code == 200, response.text
    return response.json()


def test_capabilities_publish_the_deployment_default(tmp_path):
    on = capabilities(tmp_path, settings=AssistantSettings(web_default=True))
    off = capabilities(tmp_path, settings=AssistantSettings(web_default=False))

    assert on["web"]["default_on"] is True
    assert off["web"]["default_on"] is False


def test_capabilities_publish_the_presets_from_the_config(tmp_path):
    body = capabilities(tmp_path)

    assert body["presets"]["jurisdictions"], "the shipped sample config must supply presets"
    assert body["presets"]["suggested_questions"]


# --- stubs ----------------------------------------------------------------------------------


class StubStatute:
    """Fails the statute leg so the web fallback is the only way to answer."""

    def __init__(self) -> None:
        self.calls = 0

    def search(self, principal, workspace_id, plan, applicable_on):
        return []

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        self.calls += 1
        return StatuteOutcome(status="failed", reason="corpus_updating")

    def health(self):
        return {
            "reachable": False,
            "documents": None,
            "chunks": None,
            "index_version": None,
            "jurisdictions": None,
        }


class EmptyRetriever:
    def search(self, principal, workspace_id, plan, applicable_on):
        return []


class StubWebGateway:
    supports_tool_search = True

    def __init__(self) -> None:
        self.calls = 0

    def compose(self, plan, bundle, context):
        from app.assistant.pipeline import FixtureComposer

        return FixtureComposer().compose(plan, bundle, context)

    def general_web(self, query, *, max_keyword, language):
        self.calls += 1
        return None


# --- audit ----------------------------------------------------------------------------------


def run_and_read_audit(tmp_path: Path, *, source: str | None):
    service = make_service(tmp_path, statute=StubStatute(), retriever=EmptyRetriever())
    session = service.create_session(
        PRINCIPAL, SessionCreate(workspace_id=WORKSPACE, locale="en"), "audit-s", "audit-s"
    )
    accepted = service.create_run(
        PRINCIPAL,
        session.id,
        RunCreate(question=QUESTION, web_search=False, web_search_source=source),
        "audit-r",
        "audit-r",
    )
    service.execute_run(accepted.id)
    return service.store.list_audit(accepted.id)


def succeeded_payload(events: list[dict]) -> dict:
    succeeded = [event for event in events if event["event_type"] == "run_succeeded"]
    assert succeeded, [event["event_type"] for event in events]
    return json.loads(succeeded[0]["payload_json"])


def test_the_audit_payload_carries_the_web_decision(tmp_path):
    payload = succeeded_payload(run_and_read_audit(tmp_path, source="default"))

    assert payload["web_search"] is False
    assert payload["web_source"] == "default"


def test_a_user_choice_is_recorded_as_such(tmp_path):
    payload = succeeded_payload(run_and_read_audit(tmp_path, source="user"))

    assert payload["web_source"] == "user"


def test_an_unlabelled_run_is_recorded_as_unknown(tmp_path):
    payload = succeeded_payload(run_and_read_audit(tmp_path, source=None))

    assert payload["web_source"] == "unknown"


# --- regression: a deployment that switches it off keeps every search internal ---------------


def test_switching_the_default_off_keeps_every_search_internal(tmp_path):
    from app.assistant.egress import EgressPolicy

    gateway = StubWebGateway()
    settings = AssistantSettings(
        model="doubao:seed-1",
        api_key="k",
        approved_processor=True,
        general_web=True,
        web_default=False,
    )
    service = make_service(
        tmp_path,
        statute=StubStatute(),
        retriever=EmptyRetriever(),
        gateway=gateway,
        egress=EgressPolicy(version="t", allowed_domains=["iccwbo.org"]),
        settings=settings,
    )
    session = service.create_session(
        PRINCIPAL, SessionCreate(workspace_id=WORKSPACE, locale="en"), "off-s", "off-s"
    )
    accepted = service.create_run(
        PRINCIPAL, session.id, RunCreate(question=QUESTION, web_search=False), "off-r", "off-r"
    )
    service.execute_run(accepted.id)
    run = service.get_run(PRINCIPAL, accepted.id)

    assert gateway.calls == 0
    assert all(layer.layer != "web" for layer in run.result.retrieval)