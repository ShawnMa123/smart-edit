"""Seed a *real* automation demo: template → binding → shadow rule → approved submission → shadowed job.

Run on the host that owns the database (the demo server, or a copy):

    SMART_EDIT_HOST_DB=/opt/smart-edit/data/host.db \
      .venv/bin/python scripts/seed_automation_demo.py

Why this exists: Rules/Runs are server state produced by a workflow, so a fresh demo shows empty
panels and the guided tour has nothing concrete to point at. This script walks the normal path —
create a document, bind a template, submit, approve twice, let the worker plan — so the panels show
a real rule and a real job. Nothing is sent: the rule is `shadow` and the script refuses to run when
another matching rule could send.

Idempotent: the demo document uses a fixed id, the rule is reused by name, and the worker's
`(rule, submission)` idempotency key stops duplicate jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.automation.registry import AutomationRegistry
from app.automation.registry_schemas import TemplateBindRequest
from app.automation.rule_schemas import RuleCreate
from app.automation.rules import AutomationRuleService
from app.automation.worker import AutomationWorker
from app.documents.bootstrap import build_host_services
from app.shared.ports import Principal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEXT = ROOT / "fixtures" / "automation-samples" / "trade-application.txt"
DEMO_DOCUMENT_ID = "doc_automation_demo"
DEMO_TITLE = "Automation demo · trade application"

APPLICANT = Principal(
    user_id="usr_automation_applicant",
    workspace_id="",
    roles=("applicant",),
    capabilities=("read", "use_ai", "confirm_fields", "edit", "apply", "automation_view"),
)
OPS = Principal(
    user_id="usr_automation_bankops",
    workspace_id="",
    roles=("bank_ops",),
    capabilities=(
        "read",
        "document_read",
        "document_edit",
        "automation_view",
        "automation_configure",
        "automation_dispatch",
        "automation_audit",
    ),
)
COMPLIANCE = Principal(
    user_id="usr_automation_compliance",
    workspace_id="",
    roles=("compliance",),
    capabilities=("read", "document_read", "automation_view", "automation_audit"),
)


def _principal(template: Principal, workspace: str) -> Principal:
    return Principal(
        user_id=template.user_id,
        workspace_id=workspace,
        roles=template.roles,
        capabilities=template.capabilities,
        auth_kind="system",
    )


def _pick(items, wanted: str | None, label: str):
    if not items:
        print(f"no server {label} in this workspace; create one in Automate first", file=sys.stderr)
        return None
    if wanted:
        for item in items:
            if wanted in (getattr(item, f"{label}_id", None), getattr(item, "name", None)):
                return item
        print(f"{label} {wanted!r} not found", file=sys.stderr)
        return None
    return items[0]


def _ensure_document(store, workspace: str, title: str, text: str) -> dict:
    existing = store.one("SELECT * FROM documents WHERE document_id = ?", (DEMO_DOCUMENT_ID,))
    if existing is not None:
        return existing
    return store.create_document(
        workspace_id=workspace,
        owner_user_id=APPLICANT.user_id,
        title=title,
        text=text,
        document_id=DEMO_DOCUMENT_ID,
        created_by=APPLICANT.user_id,
    )


def _ensure_rule(rules: AutomationRuleService, principal: Principal, template, connector, *, dry_run: bool):
    """A dedicated shadow rule. Refuse when any other matching rule could actually send."""
    wanted_name = f"Demo · {template.name} → {connector.name}"
    existing = [rule for rule in rules.list(principal) if rule.name == wanted_name]
    if existing:
        return existing[0]
    if dry_run:
        print(f"would create rule {wanted_name!r}")
        return None
    return rules.create(
        principal,
        RuleCreate(
            name=wanted_name,
            template_name=template.name,
            connector_id=connector.connector_id,
            mode="shadow",
            required=True,
            priority=100,
        ),
    )


def _ensure_approval(store, document: dict, *, dry_run: bool) -> str:
    """Return an approved request id, walking submit → first → second when needed."""
    latest = store.latest_request(str(document["document_id"]))
    if latest and latest["status"] == "approved":
        return str(latest["request_id"])
    if latest and latest["status"] in ("pending_first", "pending_second"):
        request_id = str(latest["request_id"])
    else:
        draft = store.find_draft_by_document(str(document["document_id"]))
        if draft is None:
            raise SystemExit("the demo document has no draft")
        if dry_run:
            print("would submit the demo document and approve it twice")
            return ""
        lock = store.acquire_lock(
            draft_id=str(draft["draft_id"]),
            owner_user_id=APPLICANT.user_id,
            lease_seconds=300,
        )
        created = store.create_submission(
            document_id=str(document["document_id"]),
            draft_id=str(draft["draft_id"]),
            submitted_by=APPLICANT.user_id,
            lock_id=str(lock["lock_id"]),
            fencing_token=int(lock["fencing_token"]),
            expected_revision=int(draft["revision"]),
            expected_sha256=draft["text_sha256"],
        )
        request_id = str(created["request"]["request_id"])

    for _ in range(2):
        request = store.get_request(request_id)
        if request is None or not str(request["status"]).startswith("pending_"):
            break
        stage = str(request["current_stage"])
        if dry_run:
            print(f"would approve stage {stage}")
            break
        actor = OPS.user_id if stage == "first" else COMPLIANCE.user_id
        store.decide_approval(
            request_id=request_id,
            stage=stage,
            decision="approve",
            actor_user_id=actor,
            comment=None,
            expected_revision=int(request["revision"]),
        )
    return request_id
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="seed the automation Rules/Runs demo")
    parser.add_argument("--workspace")
    parser.add_argument("--template", help="template name (default: first server template)")
    parser.add_argument("--connector", help="connector name or id (default: first connector)")
    parser.add_argument("--title", default=DEMO_TITLE)
    parser.add_argument("--text-file", default=str(DEFAULT_TEXT))
    parser.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    args = parser.parse_args(argv)

    host = build_host_services()
    store = host.store
    registry = AutomationRegistry(store, documents=host.documents)
    rules = AutomationRuleService(store, registry)

    row = store.one(
        "SELECT workspace_id, COUNT(*) AS n FROM documents GROUP BY workspace_id "
        "ORDER BY n DESC LIMIT 1"
    )
    workspace = args.workspace or (row["workspace_id"] if row else "ws_demo_01")
    ops = _principal(OPS, workspace)

    template = _pick(registry.list_templates(ops), args.template, "template")
    connectors = registry.list_connectors(ops)
    if not args.connector:
        # Prefer a local, allow-listed connector without a secret so `shadow` can always preview.
        connectors = sorted(
            connectors,
            key=lambda item: (
                0 if item.base_url.startswith(("http://127.0.0.1", "http://localhost")) else 1,
                0 if item.auth_kind == "none" else 1,
            ),
        )
    connector = _pick(connectors, args.connector, "connector")
    if template is None or connector is None:
        return 2

    # Safety: the worker plans one job per matching rule, so any non-shadow sibling could send.
    siblings = [
        rule
        for rule in rules.list(ops)
        if rule.template_name == template.name and rule.enabled and rule.mode != "shadow"
    ]
    if siblings:
        print(
            "refusing to seed: these matching rules could send "
            f"({', '.join(f'{rule.name}={rule.mode}' for rule in siblings)}); "
            "set them to shadow or disable them first",
            file=sys.stderr,
        )
        return 3

    text = Path(args.text_file).read_text(encoding="utf-8")
    existing_document = store.one(
        "SELECT * FROM documents WHERE document_id = ?", (DEMO_DOCUMENT_ID,)
    )
    if args.dry_run and existing_document is None:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "workspace": workspace,
                    "document": f"(would create {DEMO_DOCUMENT_ID})",
                    "template": template.name,
                    "connector": connector.name,
                    "rule": "(would create)",
                    "request": "(would submit + approve twice)",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    document = _ensure_document(store, workspace, args.title, text)
    if not document.get("template_id"):
        if args.dry_run:
            print(f"would bind {document['document_id']} to template {template.name!r}")
        else:
            registry.bind_document_template(
                ops,
                str(document["document_id"]),
                TemplateBindRequest(template_id=template.template_id),
            )

    rule = _ensure_rule(rules, ops, template, connector, dry_run=args.dry_run)
    request_id = _ensure_approval(store, document, dry_run=args.dry_run)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "workspace": workspace,
                    "document": document["document_id"],
                    "template": template.name,
                    "connector": connector.name,
                    "rule": rule.rule_id if rule else "(would create)",
                    "request": request_id or "(would approve)",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    worker = AutomationWorker(store, registry, auto_send=False)
    worker.plan_submission(request_id, "approved")
    worker.run_once()

    jobs = store.all(
        "SELECT job_id, status, mode, connector_id, rule_id, error_code "
        "FROM automation_jobs WHERE document_id = ? ORDER BY created_at DESC",
        (str(document["document_id"]),),
    )
    print(
        json.dumps(
            {
                "workspace": workspace,
                "document": document["document_id"],
                "title": document.get("title") or args.title,
                "template": template.name,
                "connector": connector.name,
                "rule": None if rule is None else rule.rule_id,
                "request": request_id,
                "jobs": [dict(job) for job in jobs],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())