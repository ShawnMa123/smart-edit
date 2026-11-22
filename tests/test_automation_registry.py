"""Server-side automation registry: variable suggestion, binding and downstream dispatch."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.automation.registry import AutomationRegistry, detect_variables
from app.automation.registry_schemas import (
    ConnectorCreate,
    ConnectorUpdate,
    DispatchRequest,
    MappingUpdate,
    PrepareRequest,
    SpecBuildRequest,
    TemplateApplyRequest,
    TemplateCreate,
    TemplateDuplicate,
    TemplateUpdate,
    TemplateVariable,
    TemplateWriteBackRequest,
    TemplateVariablesUpdate,
)
from app.documents.errors import HostError
from app.documents.store import HostStore
from app.shared.ports import Principal

TEMPLATE = """DEMAND GUARANTEE
Guarantee No: BG-2026-00417
Applicant: Alpha Tech Pte Ltd
Beneficiary: Beta Construction Ltd
Amount: {{amount}}
Currency: USD
Issue Date: {{issue_date}}
Expiry Date: {{expiry_date}}
Governing Rules: URDG 758

This guarantee is payable on first written demand.
"""

DRAFT = """DEMAND GUARANTEE
Guarantee No: BG-2026-00999
Applicant: Gamma Holdings Ltd
Beneficiary: Delta Works Ltd
Amount: USD 750,000.00
Currency: USD
Issue Date: 2027-01-05
Expiry Date: 2028-01-05
Governing Rules: URDG 758
"""


def _principal(**overrides) -> Principal:
    values = {"user_id": "usr_demo", "workspace_id": "ws_demo"}
    values.update(overrides)
    return Principal(**values)


@pytest.fixture
def registry(tmp_path) -> AutomationRegistry:
    return AutomationRegistry(HostStore(tmp_path / "host.db"))


def _template(registry: AutomationRegistry, principal: Principal, text: str = TEMPLATE) -> str:
    view = registry.create_template(
        principal,
        TemplateCreate(name="Demand guarantee", text=text, source_kind="imported"),
    )
    return view.template_id


class FakeGateway:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def compose_json(self, system, payload, *, timeout=None):
        self.calls += 1
        return self.payload


class _StubHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).received.append(
            {
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "json": json.loads(body or b"{}"),
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"accepted": true, "downstream_id": "down-1"}')

    def log_message(self, *args):  # keep pytest output clean
        return


@pytest.fixture
def stub_server():
    _StubHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, _StubHandler
    finally:
        server.shutdown()
        server.server_close()


def test_detect_variables_finds_placeholders_and_labeled_values():
    variables = {item.key: item for item in detect_variables(TEMPLATE)}

    assert variables["amount"].quote == "{{amount}}"
    assert variables["amount"].value_type == "amount"
    assert variables["amount"].required is True
    assert variables["issue_date"].value_type == "date"
    assert variables["applicant"].sample_value == "Alpha Tech Pte Ltd"
    assert variables["guarantee_no"].sample_value == "BG-2026-00417"
    assert all("payable" not in item.label.lower() for item in variables.values())


def test_detect_variables_skips_labeled_lines_that_only_hold_a_placeholder():
    """`Supplier: {{supplier_name}}` is one field, not two (`supplier` + `supplier_name`)."""
    text = "Supplier: {{supplier_name}}\nBuyer: {{buyer_name}}\nIncoterm: {{incoterm}}\n"

    assert [item.key for item in detect_variables(text)] == [
        "supplier_name",
        "buyer_name",
        "incoterm",
    ]


def test_value_type_hints_match_whole_words_only():
    """`Buyer country: Iran` is a string, not a count (`count` must not match `country`)."""
    variables = {item.key: item for item in detect_variables("Buyer country: Iran\n")}

    assert variables["buyer_country"].value_type == "string"


def test_create_suggest_save_and_list(registry):
    principal = _principal()
    template_id = _template(registry, principal)

    suggestion = registry.suggest_variables(principal, template_id, use_llm=False)
    assert suggestion.suggested_by == "deterministic"
    assert suggestion.warnings == []
    keys = {item.key for item in suggestion.variables}
    assert {"amount", "issue_date", "applicant"} <= keys

    saved = registry.save_variables(
        principal,
        template_id,
        TemplateVariablesUpdate(
            variables=[item for item in suggestion.variables if item.key in {"amount", "applicant"}]
        ),
    )
    assert saved.variables_source == "manual"
    assert {item.key for item in saved.variables} == {"amount", "applicant"}
    assert len(registry.list_templates(principal)) == 1


def test_suggestion_uses_doubao_and_keeps_verbatim_evidence(registry):
    principal = _principal()
    template_id = _template(registry, principal)
    gateway = FakeGateway(
        {
            "variables": [
                {
                    "label": "expiry_date",
                    "value_type": "date",
                    "required": True,
                    "quote": "Expiry Date: {{expiry_date}}",
                },
                {
                    "label": "advising_bank_reference",
                    "value_type": "string",
                    "required": False,
                    "quote": "text that is not in the template",
                },
            ]
        }
    )
    registry.gateway = gateway
    registry.approved = True
    registry.model_label = "doubao:test"

    suggestion = registry.suggest_variables(principal, template_id, use_llm=True)

    assert gateway.calls == 1
    assert suggestion.suggested_by == "merged"
    assert suggestion.model == "doubao:test"
    by_key = {item.key: item for item in suggestion.variables}
    assert by_key["expiry_date"].source == "deterministic"  # deterministic evidence wins
    assert by_key["advising_bank_reference"].source == "llm"
    assert by_key["advising_bank_reference"].quote is None  # unverifiable quote is dropped
    assert any(item.startswith("quote_not_found:") for item in suggestion.warnings)


def test_suggestion_folds_model_duplicates_into_one_field(registry):
    """The model renames fields the regex already read; the panel must not ask to confirm both."""
    principal = _principal()
    template_id = _template(registry, principal)
    registry.gateway = FakeGateway(
        {
            "variables": [
                {
                    "label": "applicant_name",
                    "value_type": "string",
                    "required": True,
                    "quote": "Applicant: Alpha Tech Pte Ltd",
                },
                {
                    "label": "guarantee_amount",
                    "value_type": "amount",
                    "required": True,
                    "quote": "Amount: {{amount}}",
                },
                {"label": "advising_bank", "value_type": "string", "required": False, "quote": ""},
            ]
        }
    )
    registry.approved = True
    registry.model_label = "doubao:test"

    suggestion = registry.suggest_variables(principal, template_id, use_llm=True)
    keys = [item.key for item in suggestion.variables]
    by_key = {item.key: item for item in suggestion.variables}

    assert keys.count("applicant") == 1
    assert "applicant_name" not in keys  # folded by stem
    assert "guarantee_amount" not in keys  # folded by span: same `Amount:` line
    assert "advising_bank" in keys  # a genuine addition
    assert by_key["applicant"].source == "deterministic"
    assert by_key["applicant"].required is True


def test_prepare_binds_values_from_a_draft(registry):
    principal = _principal()
    template_id = _template(registry, principal)
    suggestion = registry.suggest_variables(principal, template_id, use_llm=False)
    registry.save_variables(
        principal,
        template_id,
        TemplateVariablesUpdate(
            variables=[item for item in suggestion.variables if item.key in {"amount", "applicant"}]
        ),
    )

    prepared = registry.prepare(principal, template_id, PrepareRequest(text=DRAFT))

    assert prepared.values["amount"].value == "USD 750,000.00"
    assert prepared.values["amount"].source == "document"
    assert prepared.values["applicant"].value == "Gamma Holdings Ltd"
    assert prepared.payload["values"]["amount"] == "USD 750,000.00"
    assert prepared.missing_required == []

    empty = registry.prepare(principal, template_id, PrepareRequest(text="nothing here"))
    assert empty.values["amount"].source == "missing"
    assert set(empty.missing_required) == {"amount", "applicant"}


def test_prepare_matches_placeholder_labels_against_short_draft_labels(registry):
    """`applicant_name` / `guarantee_amount` must bind to `Applicant:` / `Amount:` in the draft."""
    principal = _principal()
    template_id = _template(registry, principal)
    registry.save_variables(
        principal,
        template_id,
        TemplateVariablesUpdate(
            variables=[
                TemplateVariable(key="applicant_name", label="applicant_name", required=True),
                TemplateVariable(key="guarantee_amount", label="guarantee_amount", required=True),
            ]
        ),
    )

    prepared = registry.prepare(principal, template_id, PrepareRequest(text=DRAFT))

    assert prepared.values["applicant_name"].value == "Gamma Holdings Ltd"
    assert prepared.values["guarantee_amount"].value == "USD 750,000.00"
    assert prepared.missing_required == []


def _saved_template(registry: AutomationRegistry, principal: Principal) -> str:
    template_id = _template(registry, principal)
    suggestion = registry.suggest_variables(principal, template_id, use_llm=False)
    registry.save_variables(
        principal,
        template_id,
        TemplateVariablesUpdate(
            variables=[
                item for item in suggestion.variables if item.key in {"amount", "applicant"}
            ]
        ),
    )
    return template_id


def _full_template(registry: AutomationRegistry, principal: Principal) -> str:
    """Every detected variable is confirmed, so auto-mapping against a spec can be exercised."""
    template_id = _template(registry, principal)
    suggestion = registry.suggest_variables(principal, template_id, use_llm=False)
    registry.save_variables(
        principal, template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )
    return template_id


def _connector(
    registry: AutomationRegistry,
    principal: Principal,
    port: int,
    *,
    auth_kind: str = "none",
    secret_env: str | None = None,
) -> str:
    view = registry.create_connector(
        principal,
        ConnectorCreate(
            name="ERP webhook",
            base_url=f"http://127.0.0.1:{port}",
            path="/hooks/guarantee",
            auth_kind=auth_kind,  # type: ignore[arg-type]
            auth_header="X-Test-Key" if auth_kind == "header" else None,
            secret_env=secret_env,
        ),
    )
    return view.connector_id


def test_connectors_keep_registration_order_so_the_default_target_is_stable(registry):
    """Adding a second connector must not re-point the panel's default send target."""
    principal = _principal()
    first = registry.create_connector(
        principal,
        ConnectorCreate(name="Primary ERP", base_url="https://erp.example.com", path="/hooks"),
    )
    second = registry.create_connector(
        principal,
        ConnectorCreate(name="Later CRM", base_url="https://crm.example.com", path="/hooks"),
    )

    listed = [item.connector_id for item in registry.list_connectors(principal)]

    assert listed == [first.connector_id, second.connector_id]


def test_dispatch_posts_the_rendered_payload(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    monkeypatch.setenv("TEST_CONNECTOR_TOKEN", "s3cret")
    connector_id = _connector(
        registry,
        principal,
        server.server_address[1],
        auth_kind="header",
        secret_env="TEST_CONNECTOR_TOKEN",
    )

    receipt = registry.dispatch(
        principal,
        DispatchRequest(
            template_id=template_id,
            connector_id=connector_id,
            values={"amount": "USD 1.00", "applicant": "Gamma Holdings Ltd"},
        ),
    )

    assert receipt.status == "succeeded"
    assert receipt.status_code == 200
    assert "downstream_id" in (receipt.response_excerpt or "")
    assert handler.received, "the stub must have received exactly the rendered payload"
    body = handler.received[0]["json"]
    assert body["values"] == {"amount": "USD 1.00", "applicant": "Gamma Holdings Ltd"}
    assert body["template"]["template_id"] == template_id
    assert handler.received[0]["headers"]["x-test-key"] == "s3cret"
    # The secret belongs to the environment, never to the stored request.
    assert "s3cret" not in json.dumps(receipt.model_dump(), ensure_ascii=False)
    assert registry.list_dispatches(principal)[0].dispatch_id == receipt.dispatch_id


def test_dispatch_refuses_a_host_that_is_not_allow_listed(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "")
    connector_id = _connector(registry, principal, server.server_address[1])

    with pytest.raises(HostError) as error:
        registry.dispatch(
            principal,
            DispatchRequest(template_id=template_id, connector_id=connector_id),
        )

    assert error.value.status == 403
    assert error.value.code == "host_not_allowed"
    assert handler.received == []
    assert registry.list_dispatches(principal)[0].status == "refused"


def test_dispatch_requires_tls_unless_http_is_explicitly_allowed(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, _handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.delenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", raising=False)
    connector_id = _connector(registry, principal, server.server_address[1])

    with pytest.raises(HostError) as error:
        registry.dispatch(
            principal, DispatchRequest(template_id=template_id, connector_id=connector_id)
        )

    assert error.value.code == "tls_required"


def test_dispatch_requires_the_secret_from_the_environment(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    connector_id = _connector(
        registry,
        principal,
        server.server_address[1],
        auth_kind="bearer",
        secret_env="MISSING_TOKEN",
    )

    with pytest.raises(HostError) as error:
        registry.dispatch(
            principal, DispatchRequest(template_id=template_id, connector_id=connector_id)
        )

    assert error.value.status == 409
    assert error.value.code == "secret_missing"
    assert handler.received == []


def test_dispatch_is_idempotent_by_key(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    connector_id = _connector(registry, principal, server.server_address[1])
    request = DispatchRequest(
        template_id=template_id,
        connector_id=connector_id,
        values={"amount": "USD 2.00"},
        idempotency_key="idem-1",
    )

    first = registry.dispatch(principal, request)
    second = registry.dispatch(principal, request)

    assert first.dispatch_id == second.dispatch_id
    assert len(handler.received) == 1
    assert len(registry.list_dispatches(principal)) == 1


SPEC_DOC = {
    "openapi": "3.0.3",
    "info": {"title": "Trade Intake API", "version": "1.4.0"},
    "paths": {
        "/trade/applications": {
            "post": {
                "operationId": "createTradeApplication",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/TradeRequest"}}
                    },
                },
            }
        }
    },
    "components": {
        "schemas": {
            "Beneficiary": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            "TradeRequest": {
                "type": "object",
                "required": ["amount"],
                "properties": {
                    "application_type": {"type": "string", "enum": ["guarantee", "standby_dc"]},
                    "amount": {"type": "number"},
                    "beneficiary": {"$ref": "#/components/schemas/Beneficiary"},
                },
            },
        }
    },
}


def _spec_connector(registry, principal, port: int) -> str:
    view = registry.create_connector(
        principal,
        ConnectorCreate(
            name="Trade intake",
            base_url=f"http://127.0.0.1:{port}",
            spec=SPEC_DOC,
        ),
    )
    return view.connector_id


def test_create_connector_takes_method_and_path_from_the_spec(registry):
    principal = _principal()

    view = registry.create_connector(
        principal,
        ConnectorCreate(name="Trade intake", base_url="https://intake.example.com", spec=SPEC_DOC),
    )

    assert view.method == "POST"
    assert view.path == "/trade/applications"  # derived: the request default "/" was not explicit
    assert view.spec_title == "Trade Intake API"
    assert view.operation == "POST /trade/applications"
    assert [item.path for item in view.request_fields] == [
        "application_type",
        "amount",
        "beneficiary.name",
    ]
    assert [item.path for item in view.request_fields if item.required] == [
        "amount",
        "beneficiary.name",
    ]


def test_create_connector_rejects_an_unusable_spec(registry):
    principal = _principal()

    with pytest.raises(HostError) as error:
        registry.create_connector(
            principal,
            ConnectorCreate(
                name="Swagger", base_url="https://x.example.com", spec={"swagger": "2.0"}
            ),
        )
    assert error.value.code == "invalid_spec"

    with pytest.raises(HostError) as unknown:
        registry.create_connector(
            principal,
            ConnectorCreate(
                name="Trade intake",
                base_url="https://x.example.com",
                spec=SPEC_DOC,
                body_map={"not_a_field": "amount"},
            ),
        )
    assert unknown.value.code == "unknown_field_path"


def test_prepare_builds_the_body_from_the_downstream_schema(registry, stub_server):
    principal = _principal()
    template_id = _full_template(registry, principal)
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])

    prepared = registry.prepare(
        principal,
        template_id,
        PrepareRequest(text=DRAFT, connector_id=connector_id),
    )

    assert prepared.connector_id == connector_id
    assert prepared.content_type == "application/json"
    assert prepared.body_mapping["beneficiary.name"] == "beneficiary"
    assert prepared.request_body == {
        "amount": 750000.0,  # number, converted from "USD 750,000.00"
        "beneficiary": {"name": "Delta Works Ltd"},
    }
    assert prepared.body_issues == []
    assert prepared.unmapped_required == []


def test_body_builder_rejects_an_enum_mismatch_and_a_bad_number():
    from app.automation.openapi import build_body, parse_spec

    operation = parse_spec(SPEC_DOC).operation("POST /trade/applications")
    assert operation is not None

    built = build_body(
        operation,
        {"application_type": "kind", "amount": "amount", "beneficiary.name": "name"},
        {"kind": "letter_of_credit", "amount": "not a number", "name": "Beta"},
    )

    assert built.ready is False
    assert built.body == {"beneficiary": {"name": "Beta"}}
    reasons = {issue["path"]: issue["reason"] for issue in built.issues}
    assert reasons == {"application_type": "invalid", "amount": "invalid"}


def test_dispatch_sends_the_spec_body_not_the_flat_envelope(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _full_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    connector_id = _spec_connector(registry, principal, server.server_address[1])

    receipt = registry.dispatch(
        principal,
        DispatchRequest(
            template_id=template_id,
            connector_id=connector_id,
            values={
                "amount": "USD 750,000.00",
                "beneficiary": "Delta Works Ltd",
                "application_type": "guarantee",
            },
        ),
    )

    assert receipt.status == "succeeded"
    body = handler.received[0]["json"]
    assert body["amount"] == 750000.0  # number, not the string "USD 750,000.00"
    assert body["beneficiary"] == {"name": "Delta Works Ltd"}
    assert "values" not in body and "template" not in body
    assert receipt.request["body"] == body
    assert receipt.request["body_mapping"]["beneficiary.name"] == "beneficiary"


def test_dispatch_refuses_an_incomplete_spec_body(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _full_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    connector_id = _spec_connector(registry, principal, server.server_address[1])
    registry.set_mapping(principal, connector_id, MappingUpdate(body_map={}))

    with pytest.raises(HostError) as error:
        registry.dispatch(
            principal,
            DispatchRequest(
                template_id=template_id,
                connector_id=connector_id,
                # Nothing bound: the required spec fields cannot be filled.
                values={},
            ),
        )

    assert error.value.status == 409
    assert error.value.code == "missing_required_body"
    assert handler.received == []
    receipt = registry.list_dispatches(principal)[0]
    assert receipt.status == "refused"
    assert receipt.error_code == "missing_required_body"


def test_an_explicitly_empty_mapping_is_not_replaced_by_suggestions(registry, stub_server):
    """Clearing every field must stick: it is a decision, not an empty box to auto-fill again."""
    principal = _principal()
    template_id = _full_template(registry, principal)
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])

    registry.set_mapping(principal, connector_id, MappingUpdate(body_map={}))
    prepared = registry.prepare(
        principal, template_id, PrepareRequest(text=DRAFT, connector_id=connector_id)
    )

    assert prepared.body_mapping == {}
    assert prepared.request_body == {}
    assert set(prepared.unmapped_required) == {"amount", "beneficiary.name"}


def test_mapping_rejects_a_path_that_is_not_in_the_operation(registry, stub_server):
    principal = _principal()
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])

    with pytest.raises(HostError) as error:
        registry.set_mapping(
            principal, connector_id, MappingUpdate(body_map={"unknown.path": "amount"})
        )

    assert error.value.status == 400
    assert error.value.code == "unknown_field_path"

    updated = registry.set_mapping(
        principal, connector_id, MappingUpdate(body_map={"amount": "amount"})
    )
    assert updated.body_map == {"amount": "amount"}


def test_update_connector_keeps_the_mapping_when_the_spec_is_unchanged(registry, stub_server):
    principal = _principal()
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])
    registry.set_mapping(principal, connector_id, MappingUpdate(body_map={"amount": "amount"}))

    updated = registry.update_connector(
        principal, connector_id, ConnectorUpdate(name="Trade intake v2", timeout_seconds=20)
    )

    assert updated.name == "Trade intake v2"
    assert updated.timeout_seconds == 20
    assert updated.body_map == {"amount": "amount"}
    assert updated.operation == "POST /trade/applications"


def test_update_connector_with_a_new_spec_resets_the_mapping(registry, stub_server):
    principal = _principal()
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])
    registry.set_mapping(principal, connector_id, MappingUpdate(body_map={"amount": "amount"}))
    other_spec = {
        "openapi": "3.0.3",
        "info": {"title": "Settlement API", "version": "2.0.0"},
        "paths": {
            "/settlements": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["reference"],
                                    "properties": {"reference": {"type": "string"}},
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    updated = registry.update_connector(
        principal, connector_id, ConnectorUpdate(spec=other_spec)
    )

    assert updated.spec_title == "Settlement API"
    assert updated.operation == "POST /settlements"
    assert updated.path == "/settlements"
    assert updated.body_map == {}
    # The stored document can be re-read for the editor.
    stored = registry.connector_spec(principal, connector_id)
    assert stored.spec["info"]["title"] == "Settlement API"
    assert stored.operation == "POST /settlements"


def test_disable_connector_hides_it_and_blocks_dispatch(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _full_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    connector_id = _spec_connector(registry, principal, server.server_address[1])

    disabled = registry.disable_connector(principal, connector_id)

    assert disabled.disabled_at is not None
    assert registry.list_connectors(principal) == []
    with pytest.raises(HostError) as error:
        registry.dispatch(
            principal,
            DispatchRequest(template_id=template_id, connector_id=connector_id, values={}),
        )
    assert error.value.status == 404
    assert handler.received == []


def test_rename_duplicate_and_delete_a_template(registry):
    principal = _principal()
    template_id = _template(registry, principal, "DEMAND GUARANTEE\nApplicant: {{applicant}}\n")

    renamed = registry.rename_template(principal, template_id, TemplateUpdate(name="Guarantee v2"))
    assert renamed.name == "Guarantee v2"
    assert renamed.template_id == template_id

    other = registry.create_template(
        principal, TemplateCreate(name="Other", text="Amount: {{amount}}")
    )
    # Renaming onto an existing (name, version) pair is refused; a plain save would bump instead.
    with pytest.raises(HostError) as clash:
        registry.rename_template(principal, other.template_id, TemplateUpdate(name="Guarantee v2"))
    assert clash.value.code == "name_taken"

    copied = registry.duplicate_template(principal, template_id, TemplateDuplicate(name="Copy"))
    assert copied.template_id != template_id
    assert copied.name == "Copy"
    assert copied.text_chars == renamed.text_chars
    assert registry.get_template(principal, copied.template_id).name == "Copy"

    registry.delete_template(principal, copied.template_id)
    assert copied.template_id not in {item.template_id for item in registry.list_templates(principal)}
    with pytest.raises(HostError) as gone:
        registry.get_template(principal, copied.template_id)
    assert gone.value.status == 404


def test_apply_template_creates_a_filled_document(tmp_path):
    from app.automation.registry import AutomationRegistry
    from app.documents.bootstrap import build_host_services

    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    principal = _principal()
    template = registry.create_template(
        principal,
        TemplateCreate(
            name="Trade application",
            text=(
                "TRADE APPLICATION\n"
                "Application type: {{kind}}\n"
                "Applicant: Alpha\n"
                "Amount: 0\n"
            ),
        ),
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )

    result = registry.apply_template(
        principal,
        template.template_id,
        TemplateApplyRequest(
            title="Application 2026-01",
            values={"kind": "guarantee", "applicant": "Beta Holdings", "amount": "USD 250,000.00"},
        ),
    )

    assert result.title == "Application 2026-01"
    assert result.filled["kind"] == "guarantee"
    assert result.missing == []
    document = host.documents.document_view(principal, result.document_id)
    assert "Application type: guarantee" in document["text"]
    assert "Applicant: Beta Holdings" in document["text"]
    assert "Amount: USD 250,000.00" in document["text"]
    assert "{{" not in document["text"]


def test_apply_template_reports_required_fields_without_a_value(tmp_path):
    from app.automation.registry import AutomationRegistry
    from app.documents.bootstrap import build_host_services

    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    principal = _principal()
    template = registry.create_template(
        principal,
        TemplateCreate(name="Guarantee", text="DEMAND GUARANTEE\nAmount: {{amount}}\n"),
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )

    result = registry.apply_template(
        principal, template.template_id, TemplateApplyRequest(values={})
    )

    assert result.missing == ["amount"]
    assert result.filled == {}


def test_hand_written_fields_behave_like_a_one_operation_spec(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _full_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    connector = registry.create_connector(
        principal,
        ConnectorCreate(
            name="Partner intake",
            base_url=f"http://127.0.0.1:{server.server_address[1]}",
            path="/intake",
            fields=[
                {"path": "amount", "type": "number", "required": True},
                {"path": "beneficiary.name", "type": "string", "required": True},
            ],
        ),
    )

    assert connector.schema_kind == "fields"
    assert [item.path for item in connector.request_fields] == ["amount", "beneficiary.name"]
    assert connector.content_type == "application/json"

    prepared = registry.prepare(
        principal, template_id, PrepareRequest(text=DRAFT, connector_id=connector.connector_id)
    )
    assert prepared.request_body == {
        "amount": 750000.0,
        "beneficiary": {"name": "Delta Works Ltd"},
    }

    receipt = registry.dispatch(
        principal,
        DispatchRequest(
            template_id=template_id,
            connector_id=connector.connector_id,
            values={"amount": "USD 750,000.00", "beneficiary": "Delta Works Ltd"},
        ),
    )
    assert receipt.status == "succeeded"
    assert handler.received[0]["json"] == {
        "amount": 750000.0,
        "beneficiary": {"name": "Delta Works Ltd"},
    }


def test_hand_written_fields_are_validated(registry):
    principal = _principal()

    with pytest.raises(HostError) as bad_path:
        registry.create_connector(
            principal,
            ConnectorCreate(
                name="Bad", base_url="https://x.example.com", fields=[{"path": "1-bad"}]
            ),
        )
    assert bad_path.value.code == "invalid_field_path"

    with pytest.raises(HostError) as duplicate:
        registry.create_connector(
            principal,
            ConnectorCreate(
                name="Dup",
                base_url="https://x.example.com",
                fields=[{"path": "amount"}, {"path": "amount"}],
            ),
        )
    assert duplicate.value.code == "duplicate_field_path"

    with pytest.raises(HostError) as conflict:
        registry.create_connector(
            principal,
            ConnectorCreate(
                name="Both",
                base_url="https://x.example.com",
                spec=SPEC_DOC,
                fields=[{"path": "amount"}],
            ),
        )
    assert conflict.value.code == "schema_conflict"


def test_preview_shows_the_request_without_calling_or_recording(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    monkeypatch.setenv("TEST_CONNECTOR_TOKEN", "s3cret")
    connector_id = _connector(
        registry,
        principal,
        server.server_address[1],
        auth_kind="header",
        secret_env="TEST_CONNECTOR_TOKEN",
    )

    preview = registry.preview(
        principal,
        DispatchRequest(
            template_id=template_id,
            connector_id=connector_id,
            values={"amount": "USD 1.00", "applicant": "Gamma Holdings Ltd"},
        ),
    )

    assert preview.url.endswith("/hooks/guarantee")
    assert preview.method == "POST"
    assert preview.headers["X-Test-Key"] == "***"  # masked, never the secret
    assert preview.headers["Content-Type"] == "application/json"
    assert preview.body["values"] == {"amount": "USD 1.00", "applicant": "Gamma Holdings Ltd"}
    assert preview.refusal is None
    assert handler.received == []
    assert registry.list_dispatches(principal) == []


def test_write_back_fills_the_current_draft_under_its_lock(tmp_path):
    from app.automation.registry import AutomationRegistry
    from app.documents.bootstrap import build_host_services
    from app.documents.schemas import LockCreate, DraftSave

    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    principal = _principal()
    created = host.documents.create_document(
        principal,
        __import__("app.documents.schemas", fromlist=["DocumentCreate"]).DocumentCreate(
            title="Draft", text="DEMAND GUARANTEE\nAmount: 0\nApplicant: Alpha\n"
        ),
        "req_test",
    )
    lock = host.documents.acquire_lock(
        principal, created["document_id"], created["draft_id"], LockCreate()
    )
    template = registry.create_template(
        principal,
        TemplateCreate(
            name="Guarantee",
            text="DEMAND GUARANTEE\nAmount: {{amount}}\nApplicant: {{applicant}}\n",
        ),
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )

    result = registry.write_back(
        principal,
        template.template_id,
        TemplateWriteBackRequest(
            document_id=created["document_id"],
            draft_id=created["draft_id"],
            lock_id=lock["lock_id"],
            fencing_token=lock["fencing_token"],
            expected_revision=created["revision"],
            values={"amount": "USD 250,000.00", "applicant": "Beta Holdings"},
        ),
    )

    assert result.applied == {"amount": "USD 250,000.00", "applicant": "Beta Holdings"}
    assert result.skipped == []
    assert result.revision == created["revision"] + 1
    view = host.documents.view(principal, created["document_id"], created["draft_id"])
    assert "Amount: USD 250,000.00" in view["text"]
    assert "Applicant: Beta Holdings" in view["text"]


def test_write_back_reports_labels_the_draft_does_not_have(tmp_path):
    from app.automation.registry import AutomationRegistry
    from app.documents.bootstrap import build_host_services
    from app.documents.schemas import DocumentCreate, LockCreate

    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    principal = _principal()
    created = host.documents.create_document(
        principal,
        DocumentCreate(title="Draft", text="DEMAND GUARANTEE\nAmount: 0\n"),
        "req_test",
    )
    template = registry.create_template(
        principal, TemplateCreate(name="Guarantee", text="DEMAND GUARANTEE\nAmount: {{amount}}\n")
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )
    lock = host.documents.acquire_lock(
        principal, created["document_id"], created["draft_id"], LockCreate()
    )

    result = registry.write_back(
        principal,
        template.template_id,
        TemplateWriteBackRequest(
            document_id=created["document_id"],
            draft_id=created["draft_id"],
            lock_id=lock["lock_id"],
            fencing_token=lock["fencing_token"],
            expected_revision=created["revision"],
            values={"amount": "USD 1.00", "beneficiary": "Nobody Ltd"},
        ),
    )

    assert result.applied == {"amount": "USD 1.00"}
    assert result.skipped == ["beneficiary"]


def test_write_back_refuses_a_stale_revision(tmp_path):
    from app.automation.registry import AutomationRegistry
    from app.documents.bootstrap import build_host_services
    from app.documents.schemas import DocumentCreate, LockCreate

    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    principal = _principal()
    created = host.documents.create_document(
        principal, DocumentCreate(title="Draft", text="Amount: 0\n"), "req_test"
    )
    template = registry.create_template(
        principal, TemplateCreate(name="Guarantee", text="Amount: {{amount}}\n")
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )
    lock = host.documents.acquire_lock(
        principal, created["document_id"], created["draft_id"], LockCreate()
    )

    with pytest.raises(HostError) as conflict:
        registry.write_back(
            principal,
            template.template_id,
            TemplateWriteBackRequest(
                document_id=created["document_id"],
                draft_id=created["draft_id"],
                lock_id=lock["lock_id"],
                fencing_token=lock["fencing_token"],
                expected_revision=created["revision"] + 5,
                values={"amount": "USD 1.00"},
            ),
        )

    assert conflict.value.status == 412
    assert conflict.value.code == "stale_draft"


def test_write_back_counts_a_value_that_is_already_correct(tmp_path):
    from app.automation.registry import AutomationRegistry
    from app.documents.bootstrap import build_host_services
    from app.documents.schemas import DocumentCreate, LockCreate

    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    principal = _principal()
    created = host.documents.create_document(
        principal, DocumentCreate(title="Draft", text="Amount: USD 1.00\n"), "req_test"
    )
    template = registry.create_template(
        principal, TemplateCreate(name="Guarantee", text="Amount: {{amount}}\n")
    )
    suggestion = registry.suggest_variables(principal, template.template_id, use_llm=False)
    registry.save_variables(
        principal, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )
    lock = host.documents.acquire_lock(
        principal, created["document_id"], created["draft_id"], LockCreate()
    )

    result = registry.write_back(
        principal,
        template.template_id,
        TemplateWriteBackRequest(
            document_id=created["document_id"],
            draft_id=created["draft_id"],
            lock_id=lock["lock_id"],
            fencing_token=lock["fencing_token"],
            expected_revision=created["revision"],
            values={"amount": "USD 1.00"},
        ),
    )

    # The label exists, so it is applied — even though the text did not change.
    assert result.applied == {"amount": "USD 1.00"}
    assert result.skipped == []


def test_mappings_are_stored_per_template_and_connector(registry, stub_server):
    principal = _principal()
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])
    template_a = _full_template(registry, principal)
    template_b = _template(
        registry, principal, "OTHER\nApplicant: {{applicant}}\nAmount: {{amount}}\n"
    )
    registry.save_variables(
        principal,
        template_b,
        TemplateVariablesUpdate(
            variables=registry.suggest_variables(principal, template_b, use_llm=False).variables
        ),
    )

    # Not configured yet → the panel would use suggestions.
    empty = registry.mapping(principal, template_a, connector_id)
    assert empty.configured is False
    assert empty.body_map == {}

    registry.set_mapping(
        principal,
        connector_id,
        MappingUpdate(template_id=template_a, body_map={"amount": "amount"}),
    )
    registry.set_mapping(
        principal,
        connector_id,
        MappingUpdate(template_id=template_b, body_map={"beneficiary.name": "applicant"}),
    )

    first = registry.mapping(principal, template_a, connector_id)
    second = registry.mapping(principal, template_b, connector_id)
    assert first.configured is True and second.configured is True
    assert first.body_map == {"amount": "amount"}
    assert second.body_map == {"beneficiary.name": "applicant"}

    # prepare uses the pair mapping for the template it was asked about.
    prepared = registry.prepare(
        principal, template_b, PrepareRequest(text=DRAFT, connector_id=connector_id)
    )
    assert prepared.body_mapping == {"beneficiary.name": "applicant"}
    assert prepared.request_body == {"beneficiary": {"name": "Gamma Holdings Ltd"}}


def test_a_pair_mapping_with_an_empty_body_map_stays_empty(registry, stub_server):
    principal = _principal()
    server, _handler = stub_server
    connector_id = _spec_connector(registry, principal, server.server_address[1])
    template_id = _full_template(registry, principal)

    registry.set_mapping(
        principal, connector_id, MappingUpdate(template_id=template_id, body_map={})
    )
    prepared = registry.prepare(
        principal, template_id, PrepareRequest(text=DRAFT, connector_id=connector_id)
    )

    assert prepared.body_mapping == {}
    assert set(prepared.unmapped_required) == {"amount", "beneficiary.name"}


def test_receipt_records_the_target_for_audit_and_replay(registry, stub_server, monkeypatch):
    principal = _principal()
    template_id = _saved_template(registry, principal)
    server, _handler = stub_server
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    connector_id = _connector(registry, principal, server.server_address[1])

    receipt = registry.dispatch(
        principal,
        DispatchRequest(
            template_id=template_id,
            connector_id=connector_id,
            values={"amount": "USD 1.00", "applicant": "Gamma Holdings Ltd"},
        ),
    )

    target = receipt.request.get("target")
    assert isinstance(target, dict)
    assert target["url"].endswith("/hooks/guarantee")
    assert target["method"] == "POST"
    assert target["schema_kind"] == "flat"
    # The receipt must be replayable: the exact body and the target are both there, the secret is not.
    sent = receipt.request.get("sent_body")
    assert isinstance(sent, dict)
    assert sent["values"] == {"amount": "USD 1.00", "applicant": "Gamma Holdings Ltd"}
    assert "s3cret" not in json.dumps(receipt.request)


def test_spec_parse_and_build_are_stateless_helpers(registry):
    principal = _principal()

    parsed = registry.parse_contract(principal, SPEC_DOC)

    assert parsed.title == "Trade Intake API"
    assert parsed.version == "1.4.0"
    operation = next(item for item in parsed.operations if item.id == "POST /trade/applications")
    assert operation.available is True
    assert [field.path for field in operation.fields] == [
        "application_type",
        "amount",
        "beneficiary.name",
    ]

    built = registry.build_contract_body(
        principal,
        SpecBuildRequest(
            spec=SPEC_DOC,
            operation="POST /trade/applications",
            mapping={"amount": "amount", "beneficiary.name": "name"},
            values={"amount": "USD 1,000.00", "name": "Delta Works Ltd"},
        ),
    )

    assert built.ready is True
    assert built.body == {"amount": 1000.0, "beneficiary": {"name": "Delta Works Ltd"}}
    # Nothing was persisted by either helper.
    assert registry.list_templates(principal) == []
    assert registry.list_connectors(principal) == []


def test_spec_helpers_reject_unusable_documents(registry):
    principal = _principal()

    with pytest.raises(HostError) as invalid:
        registry.parse_contract(principal, {"swagger": "2.0"})
    assert invalid.value.code == "invalid_spec"

    with pytest.raises(HostError) as missing:
        registry.build_contract_body(
            principal,
            SpecBuildRequest(spec=SPEC_DOC, operation="POST /nope"),
        )
    assert missing.value.code == "operation_not_found"


def test_write_paths_require_the_apply_capability(registry):
    reader = _principal(capabilities=("read",))

    with pytest.raises(HostError) as error:
        registry.create_template(reader, TemplateCreate(name="x", text="Amount: 1"))

    assert error.value.status == 403
    assert error.value.code == "capability_denied"