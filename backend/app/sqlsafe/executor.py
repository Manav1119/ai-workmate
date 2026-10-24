"""Restricted execution of *validated* SQL on the read-only role.

Guarantees per execution:
* Connection uses the ``workmate_reader`` role (SELECT on two tables only, RLS enforced).
* ``SET TRANSACTION READ ONLY`` and a per-transaction ``statement_timeout``.
* Row-level security scoped to one dataset via ``app.dataset_id`` (transaction-local).
* Results are capped at the validator's limit; truncation is reported.
* Raw database errors are logged server-side and mapped to safe, generic messages.
* Every attempt (including rejections) is written to ``app.query_audit``.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import logging
import time
from dataclasses import dataclass, field

import psycopg
from sqlalchemy import text

from app.config import get_settings
from app.db import app_tx, reader_engine
from app.logging_setup import request_id_var
from app.sqlsafe.validator import ValidationResult

log = logging.getLogger("workmate.sql")


class QueryExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    duration_ms: int
    sql: str
    warnings: list[str] = field(default_factory=list)


def _clean(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def audit(
    *, source: str, sql: str, validation_ok: bool, reasons: list[str] | None, executed: bool,
    user_id: int | None, analysis_id: int | None, dataset_id: int | None,
    row_count: int | None = None, duration_ms: int | None = None, error: str | None = None,
) -> None:
    try:
        with app_tx() as c:
            c.execute(
                text(
                    "INSERT INTO app.query_audit (request_id, user_id, analysis_id, dataset_id, source, sql_text,"
                    " sql_sha256, validation_ok, rejection_reasons, executed, row_count, duration_ms, error)"
                    " VALUES (:rid, :uid, :aid, :did, :src, :sql, :sha, :ok, CAST(:reasons AS JSONB), :ex, :rc, :ms, :err)"
                ),
                {
                    "rid": request_id_var.get(), "uid": user_id, "aid": analysis_id, "did": dataset_id,
                    "src": source, "sql": sql[:8000], "sha": hashlib.sha256(sql.encode()).hexdigest(),
                    "ok": validation_ok, "reasons": _json(reasons or []), "ex": executed, "rc": row_count,
                    "ms": duration_ms, "err": (error or None) and error[:500],
                },
            )
    except Exception:  # noqa: BLE001 - auditing must never break the request path
        log.exception("failed to write query audit record")


def _json(v) -> str:
    import json

    return json.dumps(v)


def execute_validated(
    v: ValidationResult, *, dataset_id: int, source: str, user_id: int | None = None,
    analysis_id: int | None = None, timeout_ms: int | None = None,
) -> QueryResult:
    """Execute SQL that has passed ``validate_sql``. Refuses anything else."""
    if not v.ok or not v.executable_sql:
        audit(source=source, sql=v.original_sql, validation_ok=False, reasons=v.reasons, executed=False,
              user_id=user_id, analysis_id=analysis_id, dataset_id=dataset_id)
        raise QueryExecutionError("sql_rejected", "; ".join(v.reasons) or "SQL failed validation")
    s = get_settings()
    timeout = int(timeout_ms or s.query_timeout_ms)
    sql = v.executable_sql
    start = time.perf_counter()
    try:
        raw = reader_engine().raw_connection()
        try:
            pg: psycopg.Connection = raw.driver_connection  # type: ignore[assignment]
            pg.rollback()
            with pg.transaction():
                with pg.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout),))
                    cur.execute("SELECT set_config('app.dataset_id', %s, true)", (str(int(dataset_id)),))
                    cur.execute(sql, prepare=False)  # no params -> no placeholder parsing
                    cols = [d.name for d in (cur.description or [])]
                    fetched = cur.fetchmany((v.limit_applied or s.query_row_limit) + 1)
        finally:
            raw.close()
    except psycopg.errors.QueryCanceled as e:
        ms = int((time.perf_counter() - start) * 1000)
        audit(source=source, sql=sql, validation_ok=True, reasons=None, executed=True, user_id=user_id,
              analysis_id=analysis_id, dataset_id=dataset_id, duration_ms=ms, error="timeout")
        raise QueryExecutionError("query_timeout", f"query exceeded the {timeout} ms time limit") from e
    except psycopg.errors.InsufficientPrivilege as e:
        ms = int((time.perf_counter() - start) * 1000)
        log.warning("reader privilege violation blocked: %s", str(e).splitlines()[0])
        audit(source=source, sql=sql, validation_ok=True, reasons=None, executed=True, user_id=user_id,
              analysis_id=analysis_id, dataset_id=dataset_id, duration_ms=ms, error="insufficient_privilege")
        raise QueryExecutionError("permission_denied", "the query attempted an operation that is not permitted") from e
    except psycopg.Error as e:
        ms = int((time.perf_counter() - start) * 1000)
        detail = str(e).splitlines()[0][:300]
        log.warning("analytical query failed: %s", detail)
        audit(source=source, sql=sql, validation_ok=True, reasons=None, executed=True, user_id=user_id,
              analysis_id=analysis_id, dataset_id=dataset_id, duration_ms=ms, error=detail)
        # The detail is safe to give back to the LLM repair loop (it's about the query),
        # but API responses use the generic message.
        err = QueryExecutionError("query_failed", "the database could not execute the query")
        err.detail = detail  # type: ignore[attr-defined]
        raise err from e

    ms = int((time.perf_counter() - start) * 1000)
    limit = v.limit_applied or s.query_row_limit
    truncated = len(fetched) > limit
    rows = [{c: _clean(val) for c, val in zip(cols, r)} for r in fetched[:limit]]
    warnings = []
    if truncated and v.limit_enforced:
        warnings.append(f"result truncated to {limit} rows by the row limit")
    audit(source=source, sql=sql, validation_ok=True, reasons=None, executed=True, user_id=user_id,
          analysis_id=analysis_id, dataset_id=dataset_id, row_count=len(rows), duration_ms=ms)
    return QueryResult(cols, rows, len(rows), truncated and v.limit_enforced, ms, sql, warnings)
