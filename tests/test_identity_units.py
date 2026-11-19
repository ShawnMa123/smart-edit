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


def test_role_catalog_grants_are_additive_and_no_deny_exists():
    assert "document.read" in perm.role_permissions("member")
    assert "developer.manage" in perm.role_permissions("org_admin")
    assert "developer.manage" not in perm.role_permissions("dept_admin")
    assert not any(key.startswith("deny") for key in perm.ROLE_CATALOG)


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