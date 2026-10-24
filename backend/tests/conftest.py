"""Test configuration.

Integration tests run against a real PostgreSQL (database ``workmate_test``) created with
the same bootstrap + seed scripts used in development, so permissions, RLS and SQL
execution are tested for real. Set TEST_ADMIN_DATABASE_URL etc. to override.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["ENVIRONMENT"] = "test"


def _configured(key: str, default: str) -> str:
    """Value from the environment, else backend/.env, else default.

    Postgres roles are cluster-wide, so the test database reuses the configured role
    passwords (only the database name differs) to avoid clobbering a dev setup.
    """
    if os.environ.get(key):
        return os.environ[key]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return default


def _test_db(url: str) -> str:
    from sqlalchemy.engine import make_url

    return make_url(url).set(database="workmate_test").render_as_string(hide_password=False)


os.environ["ADMIN_DATABASE_URL"] = os.environ.get("TEST_ADMIN_DATABASE_URL") or _test_db(
    _configured("ADMIN_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/workmate"))
os.environ["APP_DATABASE_URL"] = os.environ.get("TEST_APP_DATABASE_URL") or _test_db(
    _configured("APP_DATABASE_URL", "postgresql+psycopg://workmate_app:workmate_app_pw@localhost:5432/workmate"))
os.environ["READONLY_DATABASE_URL"] = os.environ.get("TEST_READONLY_DATABASE_URL") or _test_db(
    _configured("READONLY_DATABASE_URL", "postgresql+psycopg://workmate_reader:workmate_reader_pw@localhost:5432/workmate"))
os.environ["LLM_PROVIDER"] = "none"
os.environ.pop("LLM_API_KEY", None)
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef0123456789"
os.environ["ANALYSIS_RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["UPLOAD_DIR"] = str(ROOT / ".pytest_uploads")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FIXED_NOW = "2026-10-24T16:00:00+00:00"


def _db_available() -> bool:
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url

        url = make_url(os.environ["ADMIN_DATABASE_URL"]).set(database="postgres")
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


DB = _db_available()


def pytest_collection_modifyitems(config, items):
    if DB:
        return
    skip = pytest.mark.skip(reason="PostgreSQL not reachable; integration test skipped")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs PostgreSQL")


@pytest.fixture(scope="session")
def seeded_db():
    if not DB:
        pytest.skip("PostgreSQL not reachable")
    from scripts.bootstrap_db import main as bootstrap
    from seed.load import load

    bootstrap()
    from sqlalchemy import text

    from app.db import app_tx

    with app_tx() as c:  # clean slate for app state between test sessions
        c.execute(text("DELETE FROM app.reports"))
        c.execute(text("DELETE FROM app.analyses"))
        c.execute(text("DELETE FROM app.anomaly_states"))
        c.execute(text("DELETE FROM app.datasets WHERE kind = 'csv_upload'"))
        c.execute(text("DELETE FROM app.users WHERE NOT is_demo"))
        c.execute(text("UPDATE app.users SET anomaly_sensitivity = 'balanced', reporting_timezone = 'UTC'"))
    ds = load()
    return ds


@pytest.fixture()
def client(seeded_db):
    from app.main import app
    from app.security.rate_limit import limiter

    limiter.reset()
    with TestClient(app) as c:
        yield c


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def demo(client):
    r = client.post("/api/auth/demo")
    assert r.status_code == 200, r.text
    return auth_headers(r.json()["token"])


_counter = {"n": 0}


@pytest.fixture()
def make_user(client):
    def _make(name: str = "Analyst") -> dict:
        _counter["n"] += 1
        email = f"user{_counter['n']}-{os.getpid()}@example.com"
        r = client.post("/api/auth/register", json={"email": email, "password": "correct horse battery", "display_name": name})
        assert r.status_code == 201, r.text
        return auth_headers(r.json()["token"])

    return _make
