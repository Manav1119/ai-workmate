"""Create the database, least-privilege roles and apply SQL migrations.

Usage:  python -m scripts.bootstrap_db            (from backend/)

Idempotent: safe to run repeatedly. Uses ADMIN_DATABASE_URL; role passwords are
taken from APP_DATABASE_URL and READONLY_DATABASE_URL so they live only in env.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ensure_database(admin_url: str) -> None:
    url = make_url(admin_url)
    db_name = url.database
    server = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}).scalar()
        if not exists:
            c.execute(text(f'CREATE DATABASE "{db_name}"'))
            print(f"created database {db_name}")
    server.dispose()


def ensure_roles(conn, settings) -> None:
    for url_str in (settings.app_database_url, settings.readonly_database_url):
        u = make_url(url_str)
        role, pw = u.username, u.password or ""
        if not role or not role.replace("_", "").isalnum():
            raise SystemExit(f"invalid role name: {role!r}")
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            text(
                f"{verb} ROLE {role} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS "
                f"PASSWORD {_quote_literal(pw)}"
            )
        )
    db = make_url(settings.admin_database_url).database
    conn.execute(text(f'REVOKE ALL ON DATABASE "{db}" FROM PUBLIC'))
    conn.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO workmate_app, workmate_reader'))


def apply_migrations(conn) -> list[str]:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS app.schema_migrations ("
            " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    applied = {r[0] for r in conn.execute(text("SELECT name FROM app.schema_migrations"))}
    newly = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in applied and not path.name.startswith("003"):
            continue
        # 003 (grants/policies) is re-applied every time so new tables get grants.
        conn.exec_driver_sql(path.read_text())
        conn.execute(
            text("INSERT INTO app.schema_migrations(name) VALUES (:n) ON CONFLICT DO NOTHING"),
            {"n": path.name},
        )
        newly.append(path.name)
    return newly


def main() -> None:
    s = get_settings()
    ensure_database(s.admin_database_url)
    eng = create_engine(s.admin_database_url)
    with eng.begin() as conn:
        ensure_roles(conn, s)
        newly = apply_migrations(conn)
    eng.dispose()
    print("migrations applied:", ", ".join(newly) or "none (up to date)")


if __name__ == "__main__":
    main()
