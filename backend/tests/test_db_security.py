"""Database permission and execution-path tests (real PostgreSQL)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.db import app_tx
from app.sqlsafe import executor as executor_mod
from app.sqlsafe.catalog import default_catalog
from app.sqlsafe.executor import QueryExecutionError, execute_validated
from app.sqlsafe.validator import ValidationResult, validate_sql

pytestmark = pytest.mark.db
CAT = default_catalog()


@pytest.fixture()
def reader(seeded_db):
    eng = create_engine(get_settings().readonly_database_url)
    yield eng
    eng.dispose()


@pytest.mark.parametrize("stmt", [
    "INSERT INTO analytics.campaigns VALUES (1, 'X', 'x', 'x', 'x', NULL, 'active')",
    "UPDATE analytics.campaign_daily_metrics SET spend = 0",
    "DELETE FROM analytics.campaign_daily_metrics",
    "CREATE TABLE analytics.evil (x int)",
    "DROP TABLE analytics.campaigns",
    "SELECT email FROM app.users",
    "SELECT * FROM app.query_audit",
])
def test_reader_role_cannot_write_or_read_app_schema(reader, stmt):
    with reader.connect() as c:
        with pytest.raises(DBAPIError):
            c.execute(text(stmt))


def test_reader_cannot_write_even_after_requesting_read_write(reader):
    # default_transaction_read_only is only a default; grants are the real barrier
    with reader.connect() as c:
        with pytest.raises(DBAPIError):
            c.execute(text("SET TRANSACTION READ WRITE"))
            c.execute(text("DELETE FROM analytics.campaigns"))


def test_rls_scopes_reader_to_one_dataset(reader, seeded_db):
    with reader.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM analytics.campaign_daily_metrics")).scalar() == 0
        c.execute(text("SELECT set_config('app.dataset_id', :d, false)"), {"d": str(seeded_db)})
        assert c.execute(text("SELECT COUNT(*) FROM analytics.campaign_daily_metrics")).scalar() == 1065
        c.execute(text("SELECT set_config('app.dataset_id', '999999', false)"))
        assert c.execute(text("SELECT COUNT(*) FROM analytics.campaign_daily_metrics")).scalar() == 0


def test_executor_runs_validated_sql(seeded_db):
    v = validate_sql("SELECT SUM(conversions) AS conversions FROM campaign_daily_metrics", CAT, 10)
    r = execute_validated(v, dataset_id=seeded_db, source="test")
    assert r.rows[0]["conversions"] > 0 and not r.truncated


def test_executor_reports_truncation(seeded_db):
    v = validate_sql("SELECT date, campaign_id FROM campaign_daily_metrics", CAT, 5)
    r = execute_validated(v, dataset_id=seeded_db, source="test")
    assert r.row_count == 5 and r.truncated and r.warnings


def test_executor_timeout(seeded_db):
    v = validate_sql(
        "SELECT COUNT(*) AS n FROM campaign_daily_metrics a JOIN campaign_daily_metrics b ON TRUE "
        "JOIN campaign_daily_metrics c ON TRUE JOIN campaign_daily_metrics d ON TRUE", CAT, 10)
    assert v.ok
    with pytest.raises(QueryExecutionError) as e:
        execute_validated(v, dataset_id=seeded_db, source="test", timeout_ms=200)
    assert e.value.code == "query_timeout"


def test_unvalidated_sql_never_reaches_database(seeded_db, monkeypatch):
    calls = []
    monkeypatch.setattr(executor_mod, "reader_engine", lambda: calls.append(1) or (_ for _ in ()).throw(AssertionError))
    for sql in ["DELETE FROM campaigns", "SELECT email FROM app.users", "SELECT pg_sleep(5) FROM campaigns"]:
        v = validate_sql(sql, CAT, 10)
        with pytest.raises(QueryExecutionError) as e:
            execute_validated(v, dataset_id=seeded_db, source="test")
        assert e.value.code == "sql_rejected"
    # a hand-crafted "ok" result without executable SQL is also refused
    with pytest.raises(QueryExecutionError):
        execute_validated(ValidationResult(ok=False, original_sql="DROP TABLE x"), dataset_id=seeded_db, source="test")
    assert calls == []
    with app_tx() as c:
        rows = c.execute(text("SELECT executed, validation_ok FROM app.query_audit WHERE source = 'test' "
                              "AND sql_text LIKE 'DELETE FROM campaigns%' ORDER BY id DESC LIMIT 1")).one()
    assert rows == (False, False)


def test_reader_password_is_required(seeded_db):
    url = get_settings().readonly_database_url
    bad = url.replace(url.split("//")[1].split("@")[0].split(":")[1], "definitely-wrong")
    with pytest.raises(Exception):
        create_engine(bad).connect()
