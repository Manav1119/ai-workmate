import pytest

from app.sqlsafe.catalog import default_catalog
from app.sqlsafe.validator import validate_sql

CAT = default_catalog()

SAFE = [
    "SELECT SUM(spend) AS spend FROM analytics.campaign_daily_metrics WHERE date BETWEEN DATE '2026-10-01' AND DATE '2026-10-07'",
    "SELECT c.platform, SUM(m.conversions) AS conversions FROM campaign_daily_metrics m JOIN campaigns c "
    "ON c.campaign_id = m.campaign_id GROUP BY c.platform ORDER BY conversions DESC",
    "WITH w AS (SELECT DATE_TRUNC('week', date) AS wk, SUM(revenue) AS revenue FROM campaign_daily_metrics GROUP BY 1) "
    "SELECT wk, revenue FROM w ORDER BY wk",
    "SELECT campaign_id, total FROM (SELECT campaign_id, SUM(spend) AS total FROM campaign_daily_metrics GROUP BY 1) s",
    "SELECT campaign_name FROM campaigns WHERE campaign_name ILIKE '%brand%'",
    "SELECT CASE WHEN date >= DATE '2026-10-12' THEN 'current' ELSE 'comparison' END AS period, "
    "SUM(clicks) AS clicks FROM campaign_daily_metrics GROUP BY 1",
    "SELECT COUNT(*) AS n FROM campaign_daily_metrics",
]

UNSAFE = [
    ("DROP TABLE analytics.campaigns", "only SELECT"),
    ("DELETE FROM campaigns", "only SELECT"),
    ("UPDATE campaigns SET status = 'paused'", "only SELECT"),
    ("INSERT INTO campaigns (campaign_id) VALUES ('x')", "only SELECT"),
    ("TRUNCATE campaign_daily_metrics", "only SELECT"),
    ("ALTER TABLE campaigns ADD COLUMN x int", "only SELECT"),
    ("SELECT 1 FROM campaigns; DROP TABLE campaigns", "exactly one statement"),
    ("SELECT campaign_id FROM campaigns; SELECT 1", "exactly one statement"),
    ("WITH x AS (DELETE FROM campaigns RETURNING campaign_id) SELECT campaign_id FROM x", "prohibited"),
    ("SELECT campaign_id INTO stolen FROM campaigns", "prohibited"),
    ("SELECT campaign_id FROM campaigns FOR UPDATE", "prohibited"),
    ("COPY campaigns TO '/tmp/x'", "only SELECT"),
    ("SET app.dataset_id = 2", "only SELECT"),
    ("SELECT set_config('app.dataset_id', '2', true), campaign_id FROM campaigns", "not allowed"),
    ("SELECT pg_sleep(30), campaign_id FROM campaigns", "not allowed"),
    ("SELECT lo_import('/etc/passwd') FROM campaigns", "not allowed"),
    ("SELECT usename FROM pg_catalog.pg_user", "schema"),
    ("SELECT table_name FROM information_schema.tables", "schema"),
    ("SELECT email FROM app.users", "schema"),
    ("SELECT password_hash FROM users", "not in the approved schema"),
    ("SELECT dataset_id, SUM(spend) FROM campaign_daily_metrics GROUP BY 1", "identifier"),
    ("SELECT secret_column FROM campaigns", "identifier"),
    ("SELECT * FROM campaigns", "SELECT *"),
    ("SELECT c.* FROM campaigns c", "SELECT *"),
    ("SELECT n FROM generate_series(1, 10) AS g(n)", "not allowed"),
    ("WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r) SELECT n FROM r", "recursive"),
    ("SELECT campaign_id FROM campaigns LIMIT (SELECT 1)", "LIMIT"),
    ("SELECT SUM(spend) FROM campaign_daily_metrics WHERE date > CURRENT_DATE - 7", "non-deterministic"),
    ("SELECT x.campaign_id FROM campaigns x, LATERAL (SELECT 1 AS y) z", "prohibited"),
    ("EXPLAIN ANALYZE SELECT 1", "only SELECT"),
    ("SELECT campaign_id FROM other_db.analytics.campaigns", "cross-database"),
    ("", "between 1 and"),
    ("SELEC campaign_id FROM campaigns", ""),  # parse error or non-select
    ("SELECT 1", "approved table"),
    ("SELECT dblink('host=evil', 'select 1') FROM campaigns", "not allowed"),
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass_and_get_a_limit(sql):
    r = validate_sql(sql, CAT, 1000)
    assert r.ok, r.reasons
    assert "LIMIT" in r.executable_sql.upper()
    assert r.limit_applied == 1000


@pytest.mark.parametrize("sql,reason", UNSAFE)
def test_unsafe_queries_are_rejected(sql, reason):
    r = validate_sql(sql, CAT, 1000)
    assert not r.ok
    assert r.executable_sql is None
    if reason:
        assert reason.lower() in " ".join(r.reasons).lower(), r.reasons


def test_limit_is_clamped_and_comments_stripped():
    r = validate_sql("SELECT campaign_id FROM campaigns -- ; DROP TABLE campaigns\nLIMIT 50000", CAT, 100)
    assert r.ok and r.limit_applied == 100 and r.limit_enforced
    assert "DROP" not in r.executable_sql.upper() and "--" not in r.executable_sql
    r2 = validate_sql("SELECT campaign_id FROM campaigns LIMIT 5", CAT, 100)
    assert r2.limit_applied == 5 and not r2.limit_enforced


def test_checks_are_reported():
    r = validate_sql("SELECT campaign_id FROM campaigns", CAT, 10)
    names = [c["check"] for c in r.checks]
    for n in ("parse", "single_statement", "select_only", "function_allowlist", "table_allowlist",
              "identifier_validation", "column_allowlist", "row_limit"):
        assert n in names or n == "parse"
    bad = validate_sql("DELETE FROM campaigns", CAT, 10)
    assert bad.checks[-1]["passed"] is False
