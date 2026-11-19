"""PG connection pool, numbered SQL migrations and startup health check (design D10 / tasks 1.2-1.3).

Fail-closed contract: `AUTH_MODE=pg` without a reachable database raises `DatabaseUnavailable` with
an actionable message at startup. There is no fallback to the fake/SQLite identity, because that would
turn an outage into a silent authorization bypass.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg import conninfo as psycopg_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.identity.errors import DatabaseUnavailable
from app.identity.settings import AuthSettings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
SCHEMA_VERSION_KEY = "schema_version"
logger = logging.getLogger("identity.db")


def _safe_target(url: str) -> str:
    """Host/port/database only — never echo the password in an error or a log line."""
    try:
        parts = psycopg_conninfo.conninfo_to_dict(url)
    except psycopg.ProgrammingError:  # pragma: no cover - malformed URL
        return "configured database"
    host = parts.get("host") or "localhost"
    port = parts.get("port") or "5432"
    dbname = parts.get("dbname") or "postgres"
    return f"{host}:{port}/{dbname}"


def _unavailable(url: str, exc: BaseException | None = None) -> DatabaseUnavailable:
    target = _safe_target(url)
    return DatabaseUnavailable(
        f"PostgreSQL identity is enabled but {target} is not reachable. "
        "Start the tunnel (ssh -f -N team04-pg), check SMART_EDIT_DATABASE_URL, or set "
        "SMART_EDIT_AUTH_MODE=fake for a local demo. No fallback identity was started."
        + (f" (driver: {type(exc).__name__})" if exc else "")
    )


class PgDatabase:
    """Thin pool wrapper; one instance per process."""

    def __init__(self, url: str, *, settings: AuthSettings | None = None) -> None:
        self.url = url
        self._settings = settings
        self._pool: ConnectionPool | None = None
        self._target = _safe_target(url)

    # --- lifecycle ---------------------------------------------------------------------------
    def open(self, *, timeout: float | None = None) -> "PgDatabase":
        if self._pool is not None:
            return self
        pool = ConnectionPool(
            conninfo=self.url,
            min_size=self._settings.pool_min_size if self._settings else 1,
            max_size=self._settings.pool_max_size if self._settings else 8,
            timeout=timeout or (self._settings.connect_timeout if self._settings else 5),
            kwargs={"row_factory": dict_row},
            open=False,
        )
        try:
            pool.open(wait=True, timeout=timeout or 5)
            self._pool = pool
        except Exception as exc:  # psycopg_pool.PoolTimeout / OperationalError
            pool.close()
            raise _unavailable(self.url, exc) from exc
        return self

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            raise DatabaseUnavailable("PostgreSQL pool is not open; call open() during startup")
        return self._pool

    # --- health ------------------------------------------------------------------------------
    def healthcheck(self) -> None:
        """One cheap round trip; raises `DatabaseUnavailable`, never returns a \"maybe\"."""
        try:
            with self.pool.connection() as conn:
                conn.execute("SELECT 1")
        except DatabaseUnavailable:
            raise
        except Exception as exc:
            raise _unavailable(self.url, exc) from exc

    # --- query helpers -----------------------------------------------------------------------
    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        try:
            with self.pool.connection() as conn:
                yield conn
        except psycopg.OperationalError as exc:  # pool exhausted / server went away
            raise _unavailable(self.url, exc) from exc

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """One transaction: document tree, closure and version bumps commit together."""
        with self.connection() as conn:
            with conn.transaction():
                yield conn

    def execute(self, sql: str, params: tuple | dict | None = None) -> int:
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount if cursor.rowcount is not None else 0

    def fetchone(self, sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return list(conn.execute(sql, params).fetchall())


class MigrationRunner:
    """Applies `NNN_*.sql` in order; re-running is a no-op (task 1.2)."""

    def __init__(self, db: PgDatabase, directory: Path | None = None) -> None:
        self.db = db
        self.directory = directory or MIGRATIONS_DIR

    def files(self) -> list[tuple[int, Path]]:
        found: list[tuple[int, Path]] = []
        for path in sorted(self.directory.glob("*.sql")):
            prefix = path.name.split("_", 1)[0]
            if not prefix.isdigit():
                raise ValueError(f"migration {path.name} must start with a numeric prefix")
            found.append((int(prefix), path))
        versions = [version for version, _ in found]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate migration version prefix")
        return found

    def _prepare(self, conn: psycopg.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, filename TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL"
            " DEFAULT now())"
        )

    def current_version(self) -> int:
        with self.db.connection() as conn:
            self._prepare(conn)
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = %s", (SCHEMA_VERSION_KEY,)
            ).fetchone()
        try:
            return int(row["value"]) if row else 0
        except (TypeError, ValueError):
            raise DatabaseUnavailable("schema_meta.schema_version is not an integer") from None

    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self.db.connection() as conn:
            self._prepare(conn)
        for version, path in self.files():
            with self.db.transaction() as conn:
                # Re-check inside the transaction so two starters cannot apply the same file twice.
                row = conn.execute(
                    "SELECT value FROM schema_meta WHERE key = %s", (SCHEMA_VERSION_KEY,)
                ).fetchone()
                current = int(row["value"]) if row else 0
                if version <= current:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (version, filename) VALUES (%s, %s) "
                    "ON CONFLICT (version) DO NOTHING",
                    (version, path.name),
                )
                conn.execute(
                    "INSERT INTO schema_meta (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (SCHEMA_VERSION_KEY, str(version)),
                )
                applied.append(path.name)
        if applied:
            logger.info("pg migrations applied: %s", ", ".join(applied))
        return applied


__all__ = ["MIGRATIONS_DIR", "MigrationRunner", "PgDatabase", "SCHEMA_VERSION_KEY", "_safe_target"]