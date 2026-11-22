"""Bank Operations rules: one configuration per (template kind → downstream), shadow by default.

A rule never sends by itself here: it is the durable decision the worker consults. Keeping CRUD and
dry-run separate from dispatch lets Bank Ops observe a rule in `shadow` before any real call.
"""

from __future__ import annotations

from typing import Any

from app.automation.registry import AutomationRegistry
from app.automation.registry_schemas import DispatchRequest
from app.automation.rule_schemas import (
    RuleCreate,
    RuleDryRunRequest,
    RuleDryRunResult,
    RuleMode,
    RuleUpdate,
    RuleView,
)
from app.documents.errors import HostError, HostNotFound
from app.documents.store import HostStore, new_id, now_iso
from app.shared.ports import Principal

RULE_MODES = ("shadow", "needs_review", "auto_send")
RULE_TRIGGERS = ("final_approval", "manual")


class AutomationRuleService:
    def __init__(self, store: HostStore, registry: AutomationRegistry) -> None:
        self.store = store
        self.registry = registry

    # --- scope helpers (reuse the registry's department rules) --------------------------------
    @staticmethod
    def _workspace(principal: Principal) -> str:
        return AutomationRegistry._workspace(principal)

    def _row(self, principal: Principal, rule_id: str, *, write: bool = False) -> dict[str, Any]:
        row = self.store.one(
            "SELECT * FROM automation_rules WHERE rule_id = ? AND workspace_id = ?",
            (rule_id, self._workspace(principal)),
        )
        if row is None or not AutomationRegistry._can_view_department(
            principal, row.get("department_id")
        ):
            raise HostNotFound("automation rule not found")
        if write and not AutomationRegistry._can_write_department(
            principal, row.get("department_id")
        ):
            raise HostError(
                403,
                "department_scope_denied",
                "a department administrator cannot change an organisation-level rule",
            )
        return row

    def _template_versions(self, principal: Principal, template_name: str) -> list[dict[str, Any]]:
        rows = self.store.all(
            "SELECT * FROM automation_templates WHERE workspace_id = ? AND name = ? "
            "ORDER BY created_at DESC",
            (self._workspace(principal), template_name),
        )
        return [
            row
            for row in rows
            if AutomationRegistry._can_view_department(principal, row.get("department_id"))
        ]

    def _connector(self, principal: Principal, connector_id: str) -> dict[str, Any]:
        return self.registry._connector_row_for_view(principal, connector_id)

    def _warnings(self, principal: Principal, row: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        duplicates = self.store.all(
            "SELECT rule_id FROM automation_rules WHERE workspace_id = ? AND template_name = ? "
            "AND connector_id = ? AND enabled = 1 AND disabled_at IS NULL AND rule_id <> ?",
            (
                self._workspace(principal),
                row["template_name"],
                row["connector_id"],
                row["rule_id"],
            ),
        )
        if duplicates:
            warnings.append("duplicate_connector")
        if not self._template_versions(principal, row["template_name"]):
            warnings.append("template_missing")
        try:
            self._connector(principal, row["connector_id"])
        except HostNotFound:
            warnings.append("connector_missing")
        return warnings

    def _view(self, principal: Principal, row: dict[str, Any]) -> RuleView:
        try:
            connector_name = self._connector(principal, row["connector_id"])["name"]
        except HostNotFound:
            connector_name = None
        return RuleView(
            rule_id=row["rule_id"],
            name=row["name"],
            department_id=row.get("department_id"),
            template_name=row["template_name"],
            connector_id=row["connector_id"],
            connector_name=connector_name,
            trigger=row["trigger"],
            mode=row["mode"],
            required=bool(row["required"]),
            priority=int(row["priority"]),
            enabled=bool(row["enabled"]),
            disabled_at=row.get("disabled_at"),
            warnings=self._warnings(principal, row),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- CRUD ---------------------------------------------------------------------------------
    def list(self, principal: Principal) -> list[RuleView]:
        self.registry._require(principal, "automation_view")
        rows = self.store.all(
            "SELECT * FROM automation_rules WHERE workspace_id = ? "
            "ORDER BY priority ASC, name ASC, created_at ASC",
            (self._workspace(principal),),
        )
        return [
            self._view(principal, row)
            for row in rows
            if AutomationRegistry._can_view_department(principal, row.get("department_id"))
        ]

    def create(self, principal: Principal, request: RuleCreate) -> RuleView:
        self.registry._require(principal, "automation_configure")
        if not self._template_versions(principal, request.template_name):
            raise HostError(
                400,
                "template_not_found",
                "save the template first; a rule matches on its name",
            )
        self._connector(principal, request.connector_id)  # 404 when disabled/out of scope
        department_id = AutomationRegistry._department_for_create(principal, request.department_id)
        rule_id = new_id("rule")
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_rules (rule_id, workspace_id, department_id, name, enabled, "
                "priority, required, template_name, connector_id, trigger, mode, created_by, "
                "created_at, updated_at, disabled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    rule_id,
                    self._workspace(principal),
                    department_id,
                    request.name.strip(),
                    int(request.enabled),
                    int(request.priority),
                    int(request.required),
                    request.template_name.strip(),
                    request.connector_id,
                    request.trigger,
                    request.mode,
                    principal.user_id,
                    stamp,
                    stamp,
                ),
            )
        self.store.record_audit(
            event_type="automation_rule_created",
            actor=principal.user_id,
            payload={
                "rule_id": rule_id,
                "template_name": request.template_name.strip(),
                "connector_id": request.connector_id,
                "mode": request.mode,
                "department_id": department_id,
            },
        )
        return self._view(principal, self._row(principal, rule_id))

    def update(self, principal: Principal, rule_id: str, patch: RuleUpdate) -> RuleView:
        self.registry._require(principal, "automation_configure")
        row = self._row(principal, rule_id, write=True)
        connector_id = patch.connector_id or row["connector_id"]
        if patch.connector_id and patch.connector_id != row["connector_id"]:
            self._connector(principal, connector_id)
        changed = patch.model_dump(exclude_none=True)
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_rules SET name = ?, connector_id = ?, trigger = ?, mode = ?, "
                "required = ?, priority = ?, enabled = ?, updated_at = ? WHERE rule_id = ?",
                (
                    (patch.name or row["name"]).strip(),
                    connector_id,
                    patch.trigger or row["trigger"],
                    patch.mode or row["mode"],
                    int(patch.required if patch.required is not None else bool(row["required"])),
                    int(patch.priority if patch.priority is not None else row["priority"]),
                    int(patch.enabled if patch.enabled is not None else bool(row["enabled"])),
                    now_iso(),
                    rule_id,
                ),
            )
        self.store.record_audit(
            event_type="automation_rule_updated",
            actor=principal.user_id,
            payload={"rule_id": rule_id, "changes": changed},
        )
        return self._view(principal, self._row(principal, rule_id))

    def set_mode(self, principal: Principal, rule_id: str, mode: RuleMode) -> RuleView:
        self.registry._require(principal, "automation_configure")
        row = self._row(principal, rule_id, write=True)
        if mode not in RULE_MODES:
            raise HostError(400, "invalid_mode", "mode must be shadow, needs_review or auto_send")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_rules SET mode = ?, updated_at = ? WHERE rule_id = ?",
                (mode, now_iso(), rule_id),
            )
        # Tier changes are governance actions: keep who moved it and from where.
        self.store.record_audit(
            event_type="automation_rule_mode_changed",
            actor=principal.user_id,
            payload={"rule_id": rule_id, "from": row["mode"], "to": mode},
        )
        return self._view(principal, self._row(principal, rule_id))

    def delete(self, principal: Principal, rule_id: str) -> None:
        self.registry._require(principal, "automation_configure")
        self._row(principal, rule_id, write=True)
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_rules SET enabled = 0, disabled_at = ?, updated_at = ? "
                "WHERE rule_id = ?",
                (stamp, stamp, rule_id),
            )
        self.store.record_audit(
            event_type="automation_rule_deleted",
            actor=principal.user_id,
            payload={"rule_id": rule_id},
        )

    def dry_run(
        self, principal: Principal, rule_id: str, request: RuleDryRunRequest
    ) -> RuleDryRunResult:
        """Build the request a rule would send for one document — no HTTP, no receipt."""
        self.registry._require(principal, "automation_view")
        row = self._row(principal, rule_id)
        versions = self._template_versions(principal, row["template_name"])
        if not versions:
            raise HostError(409, "template_missing", "the rule's template no longer exists")
        template = versions[0]
        preview = self.registry.preview(
            principal,
            DispatchRequest(
                template_id=template["template_id"],
                connector_id=row["connector_id"],
                document_id=request.document_id,
            ),
        )
        return RuleDryRunResult(
            rule_id=rule_id,
            template_id=template["template_id"],
            template_name=row["template_name"],
            connector_id=row["connector_id"],
            mode=row["mode"],
            url=preview.url,
            method=preview.method,
            would_send=preview.body,
            issues=preview.issues,
            refusal=preview.refusal,
        )