"""Capability discovery endpoint (assistant-capabilities / design D1–D2)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.assistant.egress import EgressPolicy
from app.assistant.gateway import DoubaoGateway
from app.assistant.settings import AssistantSettings
from tests.assistant_helpers import headers, make_client, make_services


def doubao() -> DoubaoGateway:
    return DoubaoGateway(
        api_key="k",
        base_url="https://ark.example/api/v3",
        model="seed-1",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )


class StubGateway:
    """A gateway that declares the tool capability without being a Doubao instance."""

    supports_tool_search = True

    def compose(self, plan, bundle, context):  # pragma: no cover - not used here
        raise AssertionError("compose must not run")


def capabilities(tmp_path: Path, **kwargs) -> dict:
    services = make_services(
        tmp_path,
        egress=kwargs.pop("egress", None),
        settings=kwargs.pop("settings", None),
        gateway=kwargs.pop("gateway", None),
    )
    with make_client(tmp_path, services=services) as client:
        response = client.get("/assistant/capabilities", headers=headers())
    assert response.status_code == 200, response.text
    return response.json()


def test_defaults_report_nothing_external(tmp_path):
    body = capabilities(tmp_path)

    assert body["model"] == {
        "configured": False,
        "label": None,
        "approved_processor": False,
    }
    assert body["layers"] == {
        "local": True,
        "approved_web": False,
        "general_web": False,
        "statute": False,
    }
    assert body["statute"] == {
        "enabled": False,
        "reachable": False,
        "documents": None,
        "chunks": None,
        "index_version": None,
        "jurisdictions": None,
    }
    # This helper builds services without a settings object, so the deployment default is unknown and
    # reported conservatively as off; `test_capabilities_publish_the_deployment_default` covers both
    # explicit values.
    assert body["web"] == {"provider": "off", "default_on": False}
    # The repo ships `knowledge.sample.json`, so a default deployment does have a policy loaded —
    # it is a preset (domains + redaction rules), not an external call. The panel still defaults to
    # no web search unless `SMART_EDIT_ASSISTANT_WEB_DEFAULT` says otherwise.
    assert body["egress"]["loaded"] is True
    assert body["egress"]["allowed_domains"] >= 1
    assert "http://" not in json.dumps(body) and "https://" not in json.dumps(body)


def test_configured_general_channel_is_reported(tmp_path):
    body = capabilities(
        tmp_path,
        gateway=doubao(),
        settings=AssistantSettings(
            model="doubao:seed-1",
            api_key="k",
            approved_processor=True,
            general_web=True,
        ),
        egress=EgressPolicy(version="v9", allowed_domains=["a.org", "b.org"]),
    )

    assert body["model"]["configured"] is True
    assert body["model"]["label"] == "doubao:seed-1"
    assert body["model"]["approved_processor"] is True
    assert body["layers"]["general_web"] is True
    assert body["layers"]["approved_web"] is False
    assert body["egress"] == {"policy_version": "v9", "allowed_domains": 2, "loaded": True}


def test_general_web_requires_the_gateway_flag(tmp_path):
    body = capabilities(
        tmp_path,
        gateway=StubGateway(),
        settings=AssistantSettings(model=None, general_web=True, approved_processor=True),
    )
    assert body["layers"]["general_web"] is True  # stub declares the flag

    class NoToolGateway(StubGateway):
        supports_tool_search = False

    body = capabilities(
        tmp_path,
        gateway=NoToolGateway(),
        settings=AssistantSettings(general_web=True, approved_processor=True),
    )
    assert body["layers"]["general_web"] is False


def test_capabilities_do_not_leak_secrets(tmp_path):
    body = capabilities(
        tmp_path,
        gateway=doubao(),
        settings=AssistantSettings(
            model="doubao:seed-1", api_key="super-secret-key", approved_processor=True, general_web=True
        ),
        egress=EgressPolicy(version="v9", allowed_domains=["a.org"]),
    )
    serialized = json.dumps(body)

    assert "super-secret-key" not in serialized
    assert "api_key" not in serialized
    assert "token" not in serialized.lower()
    assert "http://" not in serialized and "https://" not in serialized
    assert "user_a" not in serialized