"""One factory for the identity stack (task 1.3).

`fake` mode returns no database at all; `pg` mode opens the pool, runs migrations, verifies the role
catalog and then hands out services. Startup fails loudly if PG is unreachable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.identity.activity_service import ActivityService
from app.identity.auth_service import AuthService
from app.identity.authorization import AuthorizationService
from app.identity.db import MigrationRunner, PgDatabase
from app.identity.developer_service import DeveloperService
from app.identity.org_service import OrganizationService
from app.identity.passwords import PasswordHasher
from app.identity.principal import PrincipalAdapter
from app.identity.settings import AuthSettings
from app.identity.store import IdentityStore

logger = logging.getLogger("identity.bootstrap")


@dataclass
class IdentityServices:
    settings: AuthSettings
    principal: PrincipalAdapter
    db: PgDatabase | None = None
    store: IdentityStore | None = None
    hasher: PasswordHasher | None = None
    activity: ActivityService | None = None
    authorization: AuthorizationService | None = None
    auth: AuthService | None = None
    organizations: OrganizationService | None = None
    developer: DeveloperService | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.is_pg

    def close(self) -> None:
        if self.db is not None:
            self.db.close()

    def require_pg(self) -> None:
        from app.identity.errors import IdentityError

        if not self.enabled:
            raise IdentityError(
                409,
                "AUTH_MODE_FAKE",
                "this endpoint requires SMART_EDIT_AUTH_MODE=pg; the demo identity has no accounts",
            )


def build_identity_services(
    settings: AuthSettings | None = None,
    *,
    db: PgDatabase | None = None,
    migrate: bool = True,
) -> IdentityServices:
    resolved = settings or AuthSettings.from_env()
    if not resolved.is_pg:
        logger.info("identity mode=fake (X-Demo-User only; no PG connection)")
        return IdentityServices(settings=resolved, principal=PrincipalAdapter(resolved, None))

    database = db or PgDatabase(resolved.database_url or "", settings=resolved)
    database.open()
    database.healthcheck()
    if migrate:
        MigrationRunner(database).migrate()
    store = IdentityStore(database)
    store.sync_role_catalog()
    hasher = PasswordHasher.from_env()
    authorization = AuthorizationService(store)
    activity = ActivityService(store)
    services = IdentityServices(
        settings=resolved,
        principal=PrincipalAdapter(resolved, store),
        db=database,
        store=store,
        hasher=hasher,
        activity=activity,
        authorization=authorization,
        auth=AuthService(store, hasher, resolved, activity),
        organizations=OrganizationService(store, authorization, activity, resolved),
        developer=DeveloperService(store, authorization, activity),
    )
    logger.info(
        "identity mode=pg target=%s pool=%d-%d session_ttl=%ss",
        database._target,
        resolved.pool_min_size,
        resolved.pool_max_size,
        resolved.session_ttl_seconds,
    )
    return services


__all__ = ["IdentityServices", "build_identity_services"]