"""Shared helpers for the PG identity suite.

The suite is skipped when `SMART_EDIT_DATABASE_URL` is unreachable, so `AUTH_MODE=fake` regression
stays runnable on a machine without the tunnel. When it is reachable, every test starts from empty
identity tables (the dedicated `team04` database).
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.assistant.bootstrap import build_services
from app.documents.bootstrap import build_host_services
from app.identity.bootstrap import build_identity_services
from app.identity.resources import DocumentAccess
from app.identity.settings import AuthSettings

CSRF = {"X-Requested-With": "smart-edit"}

TABLES = (
    "api_request_logs",
    "api_keys",
    "activity_reads",
    "activity_events",
    "invites",
    "role_assignments",
    "role_permissions",
    "roles",
    "memberships",
    "department_closure",
    "departments",
    "organizations",
    "login_attempts",
    "sessions",
    "users",
)


def database_url() -> str:
    url = os.environ.get("SMART_EDIT_DATABASE_URL")
    if not url:
        env_file = Path(__file__).resolve().parents[1] / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("SMART_EDIT_DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        pytest.skip("SMART_EDIT_DATABASE_URL is not configured")
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception:  # noqa: BLE001 - an unreachable tunnel skips, never fails the suite
        pytest.skip("PostgreSQL is not reachable (start the team04-pg tunnel)")
    os.environ["SMART_EDIT_DATABASE_URL"] = url
    return url


def truncate(url: str) -> None:
    with psycopg.connect(url, connect_timeout=5) as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        # The migration seeds this organisation; truncation must not hide the seed contract.
        conn.execute(
            "INSERT INTO organizations (org_id, workspace_id, name, slug) "
            "VALUES ('ws_demo_01', 'ws_demo_01', 'Demo organisation', 'demo') "
            "ON CONFLICT (org_id) DO NOTHING"
        )
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def _cheap_argon2():
    """Keep the suite fast; production values stay the defaults (`passwords.py`)."""
    os.environ.setdefault("SMART_EDIT_ARGON2_TIME_COST", "1")
    os.environ.setdefault("SMART_EDIT_ARGON2_MEMORY_COST", "8192")
    os.environ.setdefault("SMART_EDIT_ARGON2_PARALLELISM", "1")


@pytest.fixture
def identity_services():
    url = database_url()
    truncate(url)
    settings = AuthSettings.from_env(
        {
            "SMART_EDIT_AUTH_MODE": "pg",
            "SMART_EDIT_DATABASE_URL": url,
            "SMART_EDIT_AUTH_LOGIN_MAX_FAILURES": "3",
        }
    )
    services = build_identity_services(settings)
    yield services
    services.close()


@pytest.fixture
def api(identity_services, tmp_path):
    host = build_host_services(
        db_path=tmp_path / "host.db",
        identity=identity_services.principal,
        activity=identity_services.activity,
    )
    access = DocumentAccess(identity_services.store, host.store, identity_services.authorization)
    assistant = build_services(
        db_path=tmp_path / "assistant.db",
        mode="test",
        seed=False,
        identity=identity_services.principal,
        resource_authorization=access,
        evidence_authorizer=access,
        activity=identity_services.activity,
    )
    app = create_app(
        host_services=host,
        assistant_services=assistant,
        llm=None,
        identity_services=identity_services,
        runs_dir=tmp_path / "runs",
    )
    with TestClient(app) as client:
        yield client


def register(client: TestClient, email: str = "owner@example.com", password: str = "correct-horse-1", **extra):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str = "correct-horse-1"):
    return client.post("/auth/login", json={"email": email, "password": password})


def new_client(api: TestClient, app) -> TestClient:  # pragma: no cover - convenience
    return TestClient(app)


__all__ = [
    "CSRF",
    "api",
    "database_url",
    "identity_services",
    "login",
    "register",
    "truncate",
]