"""AST-based SQL validator.

Security does NOT rely on prompts or regular expressions. Every query is parsed with
sqlglot (PostgreSQL dialect) and must pass all of these checks before execution:

1. Exactly one statement; it must be a SELECT (optionally with non-recursive CTEs or
   UNION/INTERSECT/EXCEPT of SELECTs).
2. No prohibited node anywhere in the tree (DML, DDL, COPY, SET, SELECT INTO, row locks,
   table functions, VALUES, LATERAL, EXPLAIN/commands...).
3. Only allowlisted functions (aggregates, arithmetic, date truncation, CASE...). Unknown
   functions such as pg_sleep, set_config, lo_import, dblink are rejected.
4. Only allowlisted tables in the ``analytics`` schema (no system catalogs / other schemas).
5. Every column reference is resolved against the approved schema with sqlglot's
   qualifier; unknown or hidden columns (e.g. dataset_id) are rejected.
6. Size/complexity limits and an enforced LIMIT (clamped to the configured row limit).

The SQL that is executed is regenerated from the validated AST (comments stripped),
so what was validated is exactly what runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from app.sqlsafe.catalog import APPROVED_SCHEMA, APPROVED_TABLES, Catalog

MAX_SQL_CHARS = 8000
MAX_NODES = 3000
MAX_JOINS = 4
MAX_SUBQUERY_DEPTH = 4

_ALLOWED_FUNC_NAMES = {
    "Sum", "Count", "Avg", "Min", "Max", "Coalesce", "Nullif", "Round", "Abs", "Cast", "TryCast",
    "TimestampTrunc", "DateTrunc", "Extract", "Case", "If", "Greatest", "Least", "TimeToStr",
    "RowNumber", "Rank", "DenseRank", "Lag", "Lead", "FirstValue", "LastValue", "Floor", "Ceil",
    "Stddev", "StddevSamp", "StddevPop", "Variance", "VariancePop", "PercentileCont", "PercentileDisc",
    "Median", "Concat", "Lower", "Upper", "Sqrt", "Ln", "Log", "Pow", "Sign", "DateDiff", "Trim",
    "Length", "Substring", "CountIf", "SafeDivide", "Div", "Mod", "ToDouble", "Date", "Initcap",
}
ALLOWED_FUNC_TYPES = tuple(getattr(exp, n) for n in _ALLOWED_FUNC_NAMES if hasattr(exp, n))
# boolean connectors/operators are modelled as Func subclasses in sqlglot; they are not functions
_OPERATOR_TYPES = tuple(getattr(exp, n) for n in ("Connector", "Binary", "Not", "Paren", "Neg") if hasattr(exp, n))
ALLOWED_ANONYMOUS = {"date_part", "to_char", "to_date", "date_trunc", "round", "nullif"}

_PROHIBITED_NAMES = [
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable", "TruncateTable",
    "Command", "Copy", "Set", "SetItem", "Transaction", "Commit", "Rollback", "Into", "Lock",
    "Values", "Unnest", "Lateral", "Grant", "Revoke", "Use", "Pragma", "Analyze", "LoadData",
    "Describe", "Kill", "Returning", "Show", "Cache", "Uncache", "Refresh", "Attach", "Detach",
    "Execute", "Declare", "Comprehension", "TableSample",
]
PROHIBITED_TYPES = tuple(getattr(exp, n) for n in _PROHIBITED_NAMES if hasattr(exp, n))
ALLOWED_ROOTS = tuple(getattr(exp, n) for n in ("Select", "Union", "Intersect", "Except") if hasattr(exp, n))
NONDETERMINISTIC = tuple(
    getattr(exp, n) for n in ("CurrentDate", "CurrentTimestamp", "CurrentTime", "CurrentDatetime", "Rand")
    if hasattr(exp, n)
)


@dataclass
class ValidationResult:
    ok: bool
    original_sql: str
    executable_sql: str | None = None
    reasons: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    limit_applied: int | None = None
    limit_enforced: bool = False  # True when the row cap (not the query's own LIMIT) bounds the result
    checks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reasons": self.reasons,
            "tables": self.tables,
            "columns": self.columns,
            "functions": self.functions,
            "limit_applied": self.limit_applied,
            "limit_enforced": self.limit_enforced,
            "checks": self.checks,
            "executable_sql": self.executable_sql,
        }


class _Fail(Exception):
    def __init__(self, check: str, reason: str):
        super().__init__(reason)
        self.check = check
        self.reason = reason


def _depth(node: exp.Expression) -> int:
    d = 0
    p = node.parent
    while p is not None:
        if isinstance(p, (exp.Subquery, exp.CTE)):
            d += 1
        p = p.parent
    return d


def validate_sql(sql: str, catalog: Catalog, row_limit: int) -> ValidationResult:
    res = ValidationResult(ok=False, original_sql=sql)
    passed: list[dict] = []

    def check(name: str, cond: bool, reason: str) -> None:
        if not cond:
            raise _Fail(name, reason)
        passed.append({"check": name, "passed": True})

    try:
        check("input_size", isinstance(sql, str) and 0 < len(sql) <= MAX_SQL_CHARS,
              f"SQL must be between 1 and {MAX_SQL_CHARS} characters")
        check("no_control_chars", "\x00" not in sql, "SQL contains NUL bytes")
        try:
            statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
        except (ParseError, Exception) as e:  # noqa: BLE001
            raise _Fail("parse", f"SQL could not be parsed: {str(e).splitlines()[0][:200]}") from e
        check("single_statement", len(statements) == 1,
              f"exactly one statement is allowed (found {len(statements)})")
        tree = statements[0]
        check("select_only", isinstance(tree, ALLOWED_ROOTS),
              f"only SELECT queries are allowed (got {type(tree).__name__.upper()})")

        nodes = list(tree.walk())
        check("complexity", len(nodes) <= MAX_NODES, "query is too complex")
        bad = sorted({type(n).__name__ for n in nodes if isinstance(n, PROHIBITED_TYPES)})
        check("no_prohibited_constructs", not bad, f"prohibited SQL construct(s): {', '.join(bad)}")
        with_ = tree.args.get("with") or tree.find(exp.With)
        check("no_recursive_cte", not (with_ and with_.args.get("recursive")), "recursive CTEs are not allowed")
        nondet = sorted({type(n).__name__ for n in nodes if isinstance(n, NONDETERMINISTIC)})
        check("deterministic", not nondet,
              f"non-deterministic function(s) {', '.join(nondet)}; use explicit date literals instead")

        stars = [n for n in nodes if isinstance(n, exp.Star) and not isinstance(n.parent, exp.Count)]
        check("explicit_columns", not stars, "SELECT * is not allowed; list the columns explicitly")

        funcs: set[str] = set()
        disallowed: set[str] = set()
        for n in nodes:
            if isinstance(n, exp.Anonymous):
                name = str(n.name).lower()
                funcs.add(name)
                if name not in ALLOWED_ANONYMOUS:
                    disallowed.add(name)
            elif isinstance(n, exp.Func) and not isinstance(n, _OPERATOR_TYPES):
                funcs.add(n.sql_name().lower())
                if not isinstance(n, ALLOWED_FUNC_TYPES):
                    disallowed.add(n.sql_name().lower())
        check("function_allowlist", not disallowed, f"function(s) not allowed: {', '.join(sorted(disallowed))}")

        cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        tables: set[str] = set()
        for t in tree.find_all(exp.Table):
            if not isinstance(t.this, exp.Identifier):
                raise _Fail("table_allowlist", "table functions are not allowed")
            name = t.name.lower()
            schema = (t.db or "").lower()
            if t.catalog:
                raise _Fail("schema_allowlist", "cross-database references are not allowed")
            if schema and schema != APPROVED_SCHEMA:
                raise _Fail("schema_allowlist", f"schema '{schema}' is not allowed (only '{APPROVED_SCHEMA}')")
            if not schema and name in cte_names:
                continue
            if name not in APPROVED_TABLES:
                raise _Fail("table_allowlist", f"table '{name}' is not in the approved schema")
            tables.add(name)
        passed.append({"check": "table_allowlist", "passed": True})
        check("references_data", bool(tables), "query must read from an approved table")

        joins = len(list(tree.find_all(exp.Join)))
        check("join_limit", joins <= MAX_JOINS, f"too many joins ({joins} > {MAX_JOINS})")
        depth = max((_depth(n) for n in tree.find_all(exp.Select)), default=0)
        check("nesting_limit", depth <= MAX_SUBQUERY_DEPTH, "subqueries are nested too deeply")

        # Resolve identifiers against the real approved schema (scope-aware).
        try:
            qualified = qualify(
                tree.copy(),
                schema=catalog.qualify_schema(),
                db=APPROVED_SCHEMA,
                dialect="postgres",
                validate_qualify_columns=True,
                quote_identifiers=False,
                identify=False,
            )
        except (OptimizeError, Exception) as e:  # noqa: BLE001
            msg = str(e).splitlines()[0][:240]
            raise _Fail("identifier_validation", f"unknown or ambiguous identifier: {msg}") from e
        passed.append({"check": "identifier_validation", "passed": True})

        allowed_cols = {c for cols in APPROVED_TABLES.values() for c in cols}
        cols = sorted({c.name.lower() for c in qualified.find_all(exp.Column) if c.name})
        # every column that resolves to a base table must be an approved column
        for c in qualified.find_all(exp.Column):
            if c.table and c.table.lower() in tables and c.name and c.name.lower() not in allowed_cols:
                raise _Fail("column_allowlist", f"column '{c.name}' is not approved")
        passed.append({"check": "column_allowlist", "passed": True})

        # Enforce LIMIT on the outermost query.
        limit_node = tree.args.get("limit")
        applied = row_limit
        enforced = True
        if limit_node is not None:
            lit = limit_node.expression if isinstance(limit_node, exp.Limit) else None
            if not (isinstance(lit, exp.Literal) and lit.is_int):
                raise _Fail("row_limit", "LIMIT must be an integer literal")
            applied = min(int(lit.this), row_limit)
            enforced = int(lit.this) > row_limit
        offset = tree.args.get("offset")
        if offset is not None:
            o = offset.expression
            if not (isinstance(o, exp.Literal) and o.is_int and int(o.this) <= 100_000):
                raise _Fail("row_limit", "OFFSET must be an integer literal <= 100000")
        passed.append({"check": "row_limit", "passed": True})
        final = tree.copy()
        # fetch one extra row so the executor can report truncation
        final = final.limit(applied + 1, copy=False) if isinstance(final, exp.Select) else (
            exp.select("*").from_(final.subquery("q")).limit(applied + 1)
        )
        executable = final.sql(dialect="postgres", comments=False)
        res.ok = True
        res.executable_sql = executable
        res.tables = sorted(tables)
        res.columns = cols
        res.functions = sorted(funcs)
        res.limit_applied = applied
        res.limit_enforced = enforced
    except _Fail as f:
        res.reasons = [f.reason]
        passed.append({"check": f.check, "passed": False, "reason": f.reason})
    res.checks = passed
    return res


def pretty(sql: str) -> str:
    try:
        return sqlglot.transpile(sql, read="postgres", write="postgres", pretty=True)[0]
    except Exception:  # noqa: BLE001
        return sql
