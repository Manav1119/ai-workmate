"""Database engines.

Two separate connection pools enforce separation of privileges:

* ``app_engine``      — application role (app schema read/write, analytics import).
* ``reader_engine``   — read-only role used exclusively to run validated analytical SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from app.config import get_settings


@lru_cache
def app_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.app_database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "application_name": "workmate-app"},
    )


@lru_cache
def reader_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.readonly_database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "application_name": "workmate-reader"},
    )


@contextmanager
def app_tx() -> Iterator[Connection]:
    """Transaction on the application role."""
    with app_engine().begin() as conn:
        yield conn


def ping() -> dict[str, bool]:
    out = {"app_db": False, "reader_db": False}
    try:
        with app_engine().connect() as c:
            c.execute(text("SELECT 1"))
        out["app_db"] = True
    except Exception:  # noqa: BLE001 - health check reports, never raises
        pass
    try:
        with reader_engine().connect() as c:
            c.execute(text("SELECT 1"))
        out["reader_db"] = True
    except Exception:  # noqa: BLE001
        pass
    return out
