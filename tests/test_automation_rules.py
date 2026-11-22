"""Bank Ops rules: CRUD, department scope, dry-run and the shadow default."""

from __future__ import annotations

import pytest

from app.automation.registry import AutomationRegistry
from app.automation.registry_schemas import ConnectorCreate, TemplateCreate
from app.automation.rule_schemas import RuleCreate, RuleDryRunRequest, RuleUpdate
from app.automation.rules import AutomationRuleService
from app.documents.bootstrap import build_host_services
from app.documents.errors import HostError
from app.documents.schemas import DocumentCreate
from app.shared.ports import Principal


def _principal(**overrides) -> Principal:
    values = {
        "user_id": "usr_ops",
        "workspace_id": "ws_demo",
        "roles": ("bank_ops",),
        "capabilities": (
            "read",
            "automation_view",
            "automation_configure",
            "automation_dispatch",
            "automation_audit",
        ),
    }
    values.update(overrides)
    return Principal(**values)


@pytest.fixture
def services(tmp_path):
    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    rules = AutomationRuleService(host.store, registry)
    return host, registry, rules


def _template(registry, principal, name="Demand guarantee", department_id=None):
    return registry.create_template(
        principal,
        TemplateCreate(name=name, text="Amount: {{amount}}", department_id=department_id),
    )


def _connector(registry, principal, name="ERP", department_id=None):
    return registry.create_connector(
        principal,
        ConnectorCreate(
            name=name, base_url="http://127.0.0.1:18080", department_id=department_id
        ),
    )


def test_rule_defaults_to_shadow_and_audits(services):
    host, registry, rules = services
    principal = _principal()
    template = _template(registry, principal)
    connector = _connector(registry, principal)

    created = rules.create(
        principal,
        RuleCreate(
            name="Trade intake",
            template_name=template.name,
            connector_id=connector.connector_id,
        ),
    )

    assert created.mode == "shadow"
    assert created.required is True
    assert created.trigger == "final_approval"
    assert created.template_name == template.name
    assert host.store.all("SELECT * FROM host_audit WHERE event_type='automation_rule_created'")

    with pytest.raises(HostError) as missing:
        rules.create(
            principal,
            RuleCreate(name="x", template_name="Nope", connector_id=connector.connector_id),
        )
    assert missing.value.status == 400
    assert len(rules.list(principal)) == 1


def test_duplicate_connector_is_a_warning_not_a_block(services):
    _host, registry, rules = services
    principal = _principal()
    template = _template(registry, principal)
    connector = _connector(registry, principal)
    rules.create(
        principal,
        RuleCreate(name="First", template_name=template.name, connector_id=connector.connector_id),
    )
    second = rules.create(
        principal,
        RuleCreate(name="Second", template_name=template.name, connector_id=connector.connector_id),
    )

    assert "duplicate_connector" in second.warnings
    assert len(rules.list(principal)) == 2


def test_department_admin_rules_stay_in_its_department(services):
    _host, registry, rules = services
    org_admin = _principal()
    template = _template(registry, org_admin, name="Org guarantee")
    connector = _connector(registry, org_admin)
    org_rule = rules.create(
        org_admin,
        RuleCreate(
            name="Org rule", template_name=template.name, connector_id=connector.connector_id
        ),
    )

    dept_admin = _principal(roles=("dept_admin",), auth_kind="user", department_id="dept_b")
    own = rules.create(
        dept_admin,
        RuleCreate(
            name="Dept rule", template_name=template.name, connector_id=connector.connector_id
        ),
    )
    assert own.department_id == "dept_b"

    with pytest.raises(HostError) as denied:
        rules.update(dept_admin, org_rule.rule_id, RuleUpdate(name="Hijack"))
    assert denied.value.status == 403
    assert denied.value.code == "department_scope_denied"

    other_department = _principal(
        roles=("dept_admin",), auth_kind="user", department_id="dept_c"
    )
    assert all(rule.rule_id != own.rule_id for rule in rules.list(other_department))
    assert any(rule.rule_id == org_rule.rule_id for rule in rules.list(other_department))


def test_dry_run_builds_the_body_without_a_receipt(services, monkeypatch):
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    host, registry, rules = services
    principal = _principal()
    template = _template(registry, principal)
    connector = _connector(registry, principal)
    rule = rules.create(
        principal,
        RuleCreate(name="R", template_name=template.name, connector_id=connector.connector_id),
    )
    document = host.documents.create_document(
        principal, DocumentCreate(title="D", text="Amount: USD 750,000.00"), "req_doc"
    )

    result = rules.dry_run(
        principal, rule.rule_id, RuleDryRunRequest(document_id=document["document_id"])
    )

    assert result.url.startswith("http://127.0.0.1:18080")
    assert result.refusal is None
    assert result.would_send
    assert host.store.all("SELECT * FROM automation_dispatches") == []


def test_mode_change_is_audited_and_delete_disables(services):
    host, registry, rules = services
    principal = _principal()
    template = _template(registry, principal)
    connector = _connector(registry, principal)
    rule = rules.create(
        principal,
        RuleCreate(name="R", template_name=template.name, connector_id=connector.connector_id),
    )

    moved = rules.set_mode(principal, rule.rule_id, "auto_send")
    assert moved.mode == "auto_send"
    audit = host.store.all(
        "SELECT * FROM host_audit WHERE event_type='automation_rule_mode_changed'"
    )
    assert audit and '"from": "shadow"' in audit[-1]["payload_json"]
    assert '"to": "auto_send"' in audit[-1]["payload_json"]

    rules.delete(principal, rule.rule_id)
    remaining = rules.list(principal)
    assert remaining and remaining[0].enabled is False
    assert remaining[0].disabled_at is not None