"""Unit tests for identity primitives (tasks 1.4, 2.1, 4.1, 5.1, 5.4)."""

from __future__ import annotations

import pytest

from app.assistant.adapters import AssistantServices
from app.assistant.service import AssistantService
from app.identity import permissions as perm
from app.identity.authorization import AuthorizationService, ResourceScope
from app.identity.errors import Forbidden
from app.identity.passwords import Argon2Params, PasswordHasher
from app.identity.settings import AuthSettings
from app.shared.ports import Principal


def test_password_hash_is_argon2id_and_verifies():
    hasher = PasswordHasher(Argon2Params(time_cost=1, memory_cost=8192, parallelism=1))
    digest = hasher.hash("correct-horse-1")
    assert digest.startswith("$argon2id$")
    assert "correct-horse-1" not in digest
    assert hasher.verify(digest, "correct-horse-1") is True
    assert hasher.verify(digest, "wrong") is False
    assert hasher.verify("not-a-hash", "correct-horse-1") is False


def test_auth_mode_defaults_to_fake_and_rejects_invalid_values():
    assert AuthSettings.from_env({}).mode == "fake"
    assert AuthSettings.from_env({"SMART_EDIT_AUTH_MODE": "pg", "SMART_EDIT_DATABASE_URL": "postgresql://x/y"}).mode == "pg"
    with pytest.raises(ValueError):
        AuthSettings.from_env({"SMART_EDIT_AUTH_MODE": "jwt"})
    with pytest.raises(ValueError):
        AuthSettings.from_env({"SMART_EDIT_AUTH_MODE": "pg"})


def test_assistant_settings_carry_auth_mode():
    from app.assistant.settings import AssistantSettings

    assert AssistantSettings.from_env({}).auth_mode == "fake"
    assert AssistantSettings.from_env({"SMART_EDIT_AUTH_MODE": "pg"}).auth_mode == "pg"
    with pytest.raises(ValueError):
        AssistantSettings.from_env({"SMART_EDIT_AUTH_MODE": "ldap"})


def test_shared_editing_roles_and_the_counterparty_review_route():
    bank_ops = set(perm.role_permissions(perm.ROLE_BANK_OPS))
    assert perm.DOCUMENT_CREATE in bank_ops
    assert perm.DOCUMENT_EDIT in bank_ops
    assert perm.DOCUMENT_LOCK in bank_ops
    # Bank-originated drafts are submitted by Bank Operations and then reviewed by the counterparty.
    assert perm.APPROVAL_SUBMIT in bank_ops
    assert perm.APPROVAL_FIRST in bank_ops

    applicant = set(perm.role_permissions(perm.ROLE_APPLICANT))
    assert perm.APPROVAL_COUNTERPARTY in applicant
    assert perm.APPROVAL_FIRST not in applicant

    compliance = set(perm.role_permissions(perm.ROLE_COMPLIANCE))
    assert perm.DOCUMENT_CREATE not in compliance
    assert perm.DOCUMENT_EDIT not in compliance
    assert perm.APPROVAL_SECOND in compliance


def test_role_catalog_grants_are_additive_and_no_deny_exists():
    assert "document.read" in perm.role_permissions("member")
    assert "developer.manage" in perm.role_permissions("org_admin")
    assert "developer.manage" not in perm.role_permissions("dept_admin")
    assert not any(key.startswith("deny") for key in perm.ROLE_CATALOG)


def test_automation_permissions_follow_the_bank_operations_boundary():
    bank_ops = set(perm.role_permissions(perm.ROLE_BANK_OPS))
    assert {
        perm.AUTOMATION_VIEW,
        perm.AUTOMATION_CONFIGURE,
        perm.AUTOMATION_DISPATCH,
        perm.AUTOMATION_AUDIT,
    } <= bank_ops

    dept_admin = set(perm.role_permissions(perm.ROLE_DEPT_ADMIN))
    assert perm.AUTOMATION_CONFIGURE in dept_admin
    assert perm.AUTOMATION_DISPATCH in dept_admin

    for role in (perm.ROLE_APPLICANT, perm.ROLE_MEMBER):
        permissions = set(perm.role_permissions(role))
        assert not any(item.startswith("automation.") for item in permissions)

    compliance = set(perm.role_permissions(perm.ROLE_COMPLIANCE))
    assert perm.AUTOMATION_VIEW in compliance
    assert perm.AUTOMATION_AUDIT in compliance
    assert perm.AUTOMATION_CONFIGURE not in compliance
    assert perm.AUTOMATION_DISPATCH not in compliance


class _Store:
    def __init__(self, permissions: dict[tuple[str, str | None], set[str]]) -> None:
        self.permissions_map = permissions

    def permissions_for(self, user_id, org_id, department_id=None):
        return set(self.permissions_map.get((user_id, department_id), set()))

    def has_active_membership(self, org_id, user_id):
        return True

    def department_ancestors(self, department_id):
        return ["legal", department_id]


def test_authorization_matrix_and_scope():
    service = AuthorizationService(
        _Store(
            {
                ("u1", None): {"document.read"},
                ("u1", "contracts"): {"document.read", "document.edit"},
            }
        )
    )
    principal = Principal(user_id="u1", workspace_id="ws", org_id="org")
    service.authorize(principal, "document.read", ResourceScope("org", None, "ws"))
    service.authorize(principal, "document.edit", ResourceScope("org", "contracts", "ws"))
    with pytest.raises(Forbidden):
        service.authorize(principal, "document.edit", ResourceScope("org", "finance", "ws"))
    with pytest.raises(Forbidden):
        service.authorize(principal, "org.manage", ResourceScope("org", None, "ws"))


def test_api_key_scope_is_bounded_to_its_department():
    service = AuthorizationService(_Store({("key:1", None): {"document.read"}}))
    principal = Principal(
        user_id="key:1",
        workspace_id="ws",
        org_id="org",
        department_id="contracts",
        auth_kind="api_key",
        permissions=("document.read",),
    )
    service.authorize(principal, "document.read", ResourceScope("org", "contracts", "ws"))
    with pytest.raises(Forbidden):
        # `department_ancestors("finance")` does not contain `contracts`.
        service.authorize(principal, "document.read", ResourceScope("org", "finance", "ws"))


def test_legacy_api_key_scopes_map_to_view_and_dispatch_only():
    from types import SimpleNamespace

    from app.identity.principal import PrincipalAdapter, _LEGACY_SCOPE_ALIASES

    assert _LEGACY_SCOPE_ALIASES == {
        perm.AUTOMATION_USE: perm.AUTOMATION_VIEW,
        perm.AUTOMATION_APPLY: perm.AUTOMATION_DISPATCH,
    }

    class _KeyStore:
        def get_api_key_by_hash(self, _digest):
            return {
                "key_id": "key_1",
                "created_by": "usr_bank_ops",
                "org_id": "org_1",
                "department_id": None,
                "scopes_json": [perm.AUTOMATION_USE, perm.AUTOMATION_APPLY],
                "revoked_at": None,
                "expires_at": None,
            }

        def get_user(self, user_id):
            return {"user_id": user_id, "status": "active"}

        def has_active_membership(self, org_id, user_id):
            return True

        def get_organization(self, org_id):
            return {"org_id": org_id, "workspace_id": "ws_1"}

        def permissions_for(self, user_id, org_id, department_id=None):
            return {perm.DOCUMENT_READ, perm.AUTOMATION_VIEW, perm.AUTOMATION_DISPATCH}

        def authorization_version(self, org_id):
            return 3

        def touch_api_key(self, key_id):
            return None

    adapter = PrincipalAdapter(
        AuthSettings.from_env(
            {
                "SMART_EDIT_AUTH_MODE": "pg",
                "SMART_EDIT_DATABASE_URL": "postgresql://user:pass@localhost/db",
            }
        ),
        _KeyStore(),
    )
    resolved = adapter._api_key(SimpleNamespace(state=SimpleNamespace()), "sk_live_example")

    assert perm.AUTOMATION_VIEW in resolved.permissions
    assert perm.AUTOMATION_DISPATCH in resolved.permissions
    assert perm.AUTOMATION_CONFIGURE not in resolved.permissions
    assert resolved.has("automation_view")
    assert resolved.has("automation_dispatch")
    assert not resolved.has("automation_configure")


class _EvidenceAuthorizer:
    def can_read(self, principal, document_id):
        return document_id != "doc_other"


def test_automation_applicability_rejects_a_stale_authorization_version():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.automation.service import AutomationService

    service = object.__new__(AutomationService)
    service.version_provider = lambda workspace_id: "org:o:7"
    service.authorizer = None
    service.activity = None
    draft = {
        "revision": 1,
        "text_sha256": "a" * 64,
        "variables_version": 1,
        "workspace_id": "o",
    }
    model = SimpleNamespace(
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        context=SimpleNamespace(
            revision=1,
            content_sha256="a" * 64,
            variables_version=1,
            authorization_version="org:o:6",
        ),
    )
    assert service._applicability(model, draft) == "unavailable"
    model.context.authorization_version = "org:o:7"
    assert service._applicability(model, draft) == "current"


def test_assistant_evidence_is_filtered_before_composition():
    from app.assistant.ports import EvidenceBundle, EvidenceCandidate

    services = AssistantServices(
        store=object(),
        identity=object(),
        authorization=object(),
        snapshots=object(),
        audit=object(),
        clock=object(),
        retriever=object(),
        gateway=object(),
        evidence_authorizer=_EvidenceAuthorizer(),
    )
    service = AssistantService(services)
    bundle = EvidenceBundle(
        [
            EvidenceCandidate(
                citation_id="c1", source_type="document_snapshot", title="Mine",
                source_version="v1", excerpt="x", locator={}, document_id="doc_mine",
            ),
            EvidenceCandidate(
                citation_id="c2", source_type="document_snapshot", title="Other",
                source_version="v1", excerpt="y", locator={}, document_id="doc_other",
            ),
        ]
    )
    filtered = service._filter_evidence(Principal("u1", "ws"), bundle)
    assert [candidate.citation_id for candidate in filtered.candidates] == ["c1"]