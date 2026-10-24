"""Result contracts and the deterministic SQL builder.

The builder is used (a) in demo mode instead of LLM SQL generation, (b) to cross-check
the totals of LLM-generated SQL and (c) for coverage queries. All builder SQL still
passes through the same validator and read-only executor as LLM SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from app.analytics.metrics import BASE_MEASURES
from app.analytics.periods import Period
from app.pipeline.plan import QuestionPlan

SEGMENT_COLUMNS = {
    "campaign": ["campaign_id", "campaign_name", "platform"],
    "platform": ["platform"],
    "objective": ["objective"],
}
CAMPAIGN_ATTRS = {"campaign_name", "platform", "objective", "status"}


@dataclass
class Resolved:
    plan: QuestionPlan
    current: Period | None
    comparison: Period | None
    anchor: str
    notes: list[str]


def lit(v: str) -> str:
    return exp.Literal.string(str(v)).sql(dialect="postgres")


def dlit(d) -> str:
    return f"DATE {lit(d.isoformat())}"


def contract_columns(plan: QuestionPlan) -> list[str]:
    cols: list[str] = []
    if plan.intent == "compare":
        cols.append("period")
    if plan.intent == "trend":
        cols.append("date")
    seg = plan.segment_dim()
    if seg:
        cols.extend(SEGMENT_COLUMNS[seg][:1] if seg != "campaign" else ["campaign_id", "campaign_name"])
    cols.extend(BASE_MEASURES)
    return cols


def contract_text(r: Resolved) -> str:
    p = r.plan
    lines = [f"Return exactly these columns (names must match): {', '.join(contract_columns(p))}."]
    lines.append("Measures must be additive totals: SUM(spend), SUM(impressions), SUM(clicks), SUM(conversions), "
                 "SUM(revenue). Do NOT compute ratios (CPA, ROAS, rates) in SQL; the application computes them.")
    if p.intent == "compare":
        lines.append(
            f"Column period must be 'current' for dates {r.current.start} to {r.current.end} (inclusive) and "
            f"'comparison' for dates {r.comparison.start} to {r.comparison.end} (inclusive). Only include those dates."
        )
    else:
        lines.append(f"Only include dates {r.current.start} to {r.current.end} (inclusive).")
    if p.intent == "trend":
        if "week" in p.group_by:
            lines.append("Column date must be the Monday week start: CAST(DATE_TRUNC('week', date) AS DATE).")
        else:
            lines.append("Column date is the daily reporting date; one row per date.")
    seg = p.segment_dim()
    if seg:
        lines.append(f"Group by {', '.join(contract_columns(p)[: contract_columns(p).index('spend')])}.")
    if p.filters:
        for f in p.filters:
            lines.append(f"Filter: {f.dimension} in {f.values} (case-insensitive match on text values).")
    lines.append("Use explicit DATE literals. Do not use CURRENT_DATE, NOW() or SELECT *.")
    return "\n".join(lines)


def _filters_sql(plan: QuestionPlan) -> tuple[list[str], bool]:
    conds: list[str] = []
    needs_join = False
    for f in plan.filters:
        if f.dimension == "campaign_id":
            conds.append(f"m.campaign_id IN ({', '.join(lit(v) for v in f.values)})")
        else:
            needs_join = True
            vals = ", ".join(lit(v.lower()) for v in f.values)
            conds.append(f"LOWER(c.{f.dimension}) IN ({vals})")
    return conds, needs_join


def build_sql(r: Resolved) -> str:
    p = r.plan
    conds, needs_join = _filters_sql(p)
    seg = p.segment_dim()
    select: list[str] = []
    group_n = 0
    if p.intent == "compare":
        select.append(
            f"CASE WHEN m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)} "
            "THEN 'current' ELSE 'comparison' END AS period"
        )
        group_n += 1
        conds.insert(
            0,
            f"(m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)} OR "
            f"m.date BETWEEN {dlit(r.comparison.start)} AND {dlit(r.comparison.end)})",
        )
    else:
        conds.insert(0, f"m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)}")
    if p.intent == "trend":
        if "week" in p.group_by:
            select.append("CAST(DATE_TRUNC('week', m.date) AS DATE) AS date")
        else:
            select.append("m.date AS date")
        group_n += 1
    if seg:
        if seg == "campaign":
            select.extend(["m.campaign_id AS campaign_id", "c.campaign_name AS campaign_name"])
            group_n += 2
        else:
            select.append(f"c.{seg} AS {seg}")
            group_n += 1
        needs_join = True
    select.extend(f"SUM(m.{c}) AS {c}" for c in BASE_MEASURES)
    sql = "SELECT " + ", ".join(select) + " FROM analytics.campaign_daily_metrics AS m"
    if needs_join:
        sql += " JOIN analytics.campaigns AS c ON c.campaign_id = m.campaign_id"
    sql += " WHERE " + " AND ".join(conds)
    if group_n:
        sql += " GROUP BY " + ", ".join(str(i) for i in range(1, group_n + 1))
        sql += " ORDER BY " + ", ".join(str(i) for i in range(1, group_n + 1))
    return sql


def build_totals_sql(r: Resolved) -> str:
    """Cross-check query: per-period (or whole-range) totals with the same filters."""
    p = r.plan
    conds, needs_join = _filters_sql(p)
    if p.intent == "compare":
        sel = (f"CASE WHEN m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)} "
               "THEN 'current' ELSE 'comparison' END AS period, ")
        conds.insert(0, f"(m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)} OR "
                        f"m.date BETWEEN {dlit(r.comparison.start)} AND {dlit(r.comparison.end)})")
        group = " GROUP BY 1"
    else:
        sel = "'current' AS period, "
        conds.insert(0, f"m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)}")
        group = ""
    sql = "SELECT " + sel + ", ".join(f"SUM(m.{c}) AS {c}" for c in BASE_MEASURES)
    sql += " FROM analytics.campaign_daily_metrics AS m"
    if needs_join:
        sql += " JOIN analytics.campaigns AS c ON c.campaign_id = m.campaign_id"
    return sql + " WHERE " + " AND ".join(conds) + group


def build_coverage_sql(r: Resolved) -> str:
    """Per-campaign row coverage inside the analysed period(s)."""
    p = r.plan
    conds, _ = _filters_sql(p)
    cur = f"m.date BETWEEN {dlit(r.current.start)} AND {dlit(r.current.end)}"
    cmp_ = (f"m.date BETWEEN {dlit(r.comparison.start)} AND {dlit(r.comparison.end)}" if r.comparison else "FALSE")
    where = " AND ".join(conds) if conds else "TRUE"
    return (
        "SELECT c.campaign_id AS campaign_id, c.campaign_name AS campaign_name, c.status AS status, "
        "MIN(m.date) AS first_date, MAX(m.date) AS last_date, "
        f"COUNT(*) FILTER (WHERE {cur}) AS current_days, "
        f"COUNT(*) FILTER (WHERE {cmp_}) AS comparison_days "
        "FROM analytics.campaigns AS c JOIN analytics.campaign_daily_metrics AS m ON m.campaign_id = c.campaign_id "
        f"WHERE {where} GROUP BY 1, 2, 3 ORDER BY 1"
    )
