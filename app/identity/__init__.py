"""PG-backed identity, organization and authorization services (user-management).

Public surface:
- `settings.AuthSettings` / `AuthSettings.from_env()`: `SMART_EDIT_AUTH_MODE=fake|pg`.
- `bootstrap.build_identity_services()`: the one factory the API and host services share.
- `service.*Service`: auth, organization, membership/invite, authorization, activity, developer.

`fake` keeps the pre-existing `X-Demo-User` behaviour so the existing suite runs without PG.
"""

from app.identity.settings import AUTH_MODE_ENV, AuthSettings

__all__ = ["AUTH_MODE_ENV", "AuthSettings"]