"""Registration, login, sessions and organisation switching (design D1/D11, tasks 2.2-2.3/3.3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.identity.errors import (
    AuthRequired,
    Conflict,
    Forbidden,
    InvalidCredentials,
    InvalidRequest,
    RateLimited,
)
from app.identity.passwords import MIN_PASSWORD_LENGTH, PasswordHasher
from app.identity.settings import AuthSettings
from app.identity.store import IdentityStore, new_id
from app.identity.tokens import hash_token, new_token
from app.shared.ports import Principal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_email(value: str) -> bool:
    value = value.strip()
    return "@" in value and " " not in value and 3 <= len(value) <= 254


class AuthService:
    def __init__(
        self,
        store: IdentityStore,
        hasher: PasswordHasher,
        settings: AuthSettings,
        activity: Any | None = None,
    ) -> None:
        self.store = store
        self.hasher = hasher
        self.settings = settings
        self.activity = activity

    # --- helpers ------------------------------------------------------------------------------
    def _new_session(self, user_id: str, org_id: str | None, request) -> tuple[str, dict[str, Any]]:
        token = new_token()
        session = self.store.create_session(
            session_id=new_id("ses"),
            user_id=user_id,
            token_hash=hash_token(token),
            active_org_id=org_id,
            expires_at=_now() + timedelta(seconds=self.settings.session_ttl_seconds),
            user_agent=(request.headers.get("user-agent") or "")[:400] or None,
            ip=request.client.host if request.client else None,
        )
        return token, session

    def _profile(self, user: dict[str, Any], org_id: str | None) -> dict[str, Any]:
        organizations = self.store.list_organizations_for_user(user["user_id"])
        active = next((item for item in organizations if item["org_id"] == org_id), None)
        if active is None and organizations:
            active = organizations[0]
        membership = (
            self.store.get_membership(active["org_id"], user["user_id"]) if active else None
        ) or {}
        permissions = (
            sorted(self.store.permissions_for(user["user_id"], active["org_id"], None))
            if active
            else []
        )
        return {
            "user": {
                "user_id": user["user_id"],
                "email": user["email"],
                "display_name": user["display_name"],
            },
            "active_org": active,
            "active_department_id": membership.get("department_id"),
            "organizations": organizations,
            "roles": self.store.roles_for(user["user_id"], active["org_id"]) if active else [],
            "permissions": permissions,
        }

    def _record(self, org_id: str, user: dict[str, Any], action: str) -> None:
        if self.activity is None:
            return
        self.activity.safe_record(
            org_id=org_id,
            department_id=None,
            actor_user_id=user["user_id"],
            actor_label=user["display_name"],
            kind="auth",
            action=action,
            resource_type="user",
            resource_id=user["user_id"],
        )

    # --- commands -----------------------------------------------------------------------------
    def register(self, request, payload: dict[str, Any]) -> dict[str, Any]:
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""
        display_name = (payload.get("display_name") or "").strip() or email.split("@")[0]
        if not _valid_email(email):
            raise InvalidRequest("a valid email address is required")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidRequest(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
        if self.store.get_user_by_email(email):
            raise Conflict("email_taken", "an account with this email already exists")
        user = self.store.create_user(
            user_id=new_id("usr"),
            email=email,
            password_hash=self.hasher.hash(password),
            display_name=display_name,
        )
        organization = self.store.create_organization(
            org_id=new_id("org"),
            name=payload.get("organization_name") or f"{display_name}'s workspace",
            slug=None,
            owner_user_id=user["user_id"],
        )
        token, session = self._new_session(user["user_id"], organization["org_id"], request)
        self._record(organization["org_id"], user, "account registered")
        return {
            **self._profile(user, organization["org_id"]),
            "session_token": token,
            "session": {key: session[key] for key in ("session_id", "expires_at")},
        }

    def login(self, request, payload: dict[str, Any]) -> dict[str, Any]:
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""
        ip = request.client.host if request.client else "unknown"
        since = _now() - timedelta(seconds=self.settings.login_window_seconds)
        if self.store.recent_failure_count(ip, email, since) >= self.settings.login_max_failures:
            raise RateLimited(self.settings.login_window_seconds)
        user = self.store.get_user_by_email(email)
        if not user or user.get("status") != "active":
            self.store.record_login_failure(ip, email)
            raise InvalidCredentials()
        if not self.hasher.verify(user["password_hash"], password):
            self.store.record_login_failure(ip, email)
            raise InvalidCredentials()
        self.store.clear_login_failures(ip, email)
        organizations = self.store.list_organizations_for_user(user["user_id"])
        token, session = self._new_session(
            user["user_id"], organizations[0]["org_id"] if organizations else None, request
        )
        if organizations:
            self._record(organizations[0]["org_id"], user, "signed in")
        return {
            **self._profile(user, session.get("active_org_id")),
            "session_token": token,
            "session": {key: session[key] for key in ("session_id", "expires_at")},
        }

    def current_session(self, request) -> dict[str, Any]:
        session = getattr(request.state, "session", None)
        if not session:
            raise AuthRequired()
        return session

    def me(self, principal: Principal) -> dict[str, Any]:
        user = self.store.get_user(principal.user_id)
        if not user:
            raise AuthRequired()
        return self._profile(user, principal.org_id)

    def logout(self, request) -> None:
        session = self.current_session(request)
        self.store.revoke_session(session["session_id"])
        if session.get("active_org_id"):
            user = self.store.get_user(session["user_id"])
            if user:
                self._record(session["active_org_id"], user, "signed out")

    def logout_all(self, principal: Principal) -> int:
        count = self.store.revoke_all_sessions(principal.user_id)
        if principal.org_id:
            user = self.store.get_user(principal.user_id)
            if user:
                self._record(principal.org_id, user, "signed out of all devices")
        return count

    def switch_org(self, request, principal: Principal, org_id: str) -> dict[str, Any]:
        """Re-validate active membership server-side; a failed switch keeps the old org (task 3.3)."""
        if not self.store.has_active_membership(org_id, principal.user_id):
            raise Forbidden("you are not an active member of that organisation")
        organization = self.store.get_organization(org_id)
        if not organization:
            raise Forbidden()
        session = self.current_session(request)
        self.store.set_active_org(session["session_id"], org_id)
        request.state.principal = None
        user = self.store.get_user(principal.user_id)
        if not user:
            raise AuthRequired()
        return self._profile(user, org_id)


__all__ = ["AuthService"]