"""Builders for automatic-dispatch tests: real host store, fake downstream only at the edge."""

from __future__ import annotations

import json
from typing import Any

from app.automation.registry import AutomationRegistry
from app.automation.registry_schemas import (
    ConnectorCreate,
    TemplateCreate,
    TemplateVariablesUpdate,
)
from app.automation.rule_schemas import RuleCreate
from app.automation.rules import AutomationRuleService
from app.documents.bootstrap import build_host_services
from app.documents.schemas import DocumentCreate
from app.documents.store import new_id, now_iso
from app.shared.ports import Principal


def principal(**overrides: Any) -> Principal:
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


def approve(host, document_id: str, text: str) -> str:
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


def connector(registry: AutomationRegistry, owner: Principal, name: str = "ERP", path: str = "/hooks"):
    return registry.create_connector(
        owner, ConnectorCreate(name=name, base_url="http://127.0.0.1:18080", path=path)
    )


def rule(
    rules: AutomationRuleService,
    owner: Principal,
    template,
    connector_view,
    *,
    mode: str = "shadow",
    required: bool = True,
):
    return rules.create(
        owner,
        RuleCreate(
            name=f"{connector_view.name} {mode} rule",
            template_name=template.name,
            connector_id=connector_view.connector_id,
            mode=mode,
            required=required,
        ),
    )


class FakeActivity:
    """Records `safe_record` calls so tests can assert on the activity contract."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def safe_record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class FakeAuthorizer:
    def __init__(self, org_id: str = "org_demo") -> None:
        self.org_id = org_id

    def organization(self, workspace_id: str) -> dict[str, Any] | None:
        return {"org_id": self.org_id, "workspace_id": workspace_id}


def build(tmp_path, monkeypatch):
    """A bank-ops fixture: template + bound document + connector + registry/rules + store."""
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("SMART_EDIT_AUTOMATION_ALLOW_HTTP", "1")
    host = build_host_services(db_path=tmp_path / "host.db", mode="local")
    registry = AutomationRegistry(host.store, documents=host.documents)
    rules = AutomationRuleService(host.store, registry)
    owner = principal()
    template = registry.create_template(
        owner, TemplateCreate(name="Demand guarantee", text="Amount: {{amount}}")
    )
    suggestion = registry.suggest_variables(owner, template.template_id, use_llm=False)
    registry.save_variables(
        owner, template.template_id, TemplateVariablesUpdate(variables=suggestion.variables)
    )
    document = host.documents.create_document(
        owner, DocumentCreate(title="G", text="Amount: USD 750,000.00"), "req_doc"
    )
    host.store.bind_document_template(
        document_id=document["document_id"],
        workspace_id="ws_demo",
        template_id=template.template_id,
        template_name=template.name,
        actor=owner.user_id,
    )
    return {
        "host": host,
        "registry": registry,
        "rules": rules,
        "principal": owner,
        "template": template,
        "document": document,
    }