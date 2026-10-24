"""The auditable 10-step analysis pipeline.

 1 schema discovery      2 question interpretation   3 SQL generation      4 SQL validation
 5 query execution       6 result validation         7 deterministic calcs 8 explanation
 9 response validation  10 presentation (persisted record returned to the client)

LLM mode uses the configured provider for steps 2, 3 and 8. DEMO mode (no API key) uses
a rule-based interpreter, the deterministic SQL builder and a deterministic narrator, and
reports ``mode = "demo"`` with zero LLM calls. Both modes share steps 4-7 and 9 exactly.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime

from pydantic import ValidationError
from sqlalchemy import text

from app.analytics import anomalies as anomaly_engine
from app.analytics.metrics import BASE_MEASURES, METRICS, format_value
from app.analytics.periods import PeriodError, anchor_date, comparison_for, coverage_issue, resolve
from app.config import get_settings
from app.db import app_tx
from app.llm import prompts
from app.llm.base import LLMError, LLMProvider, UsageTracker
from app.pipeline import compute as comp
from app.pipeline.demo_planner import interpret as demo_interpret
from app.pipeline.explain import ExplanationDraft, finalize
from app.pipeline.narrate import narrate
from app.pipeline.plan import QuestionPlan
from app.pipeline.sqlbuild import Resolved, build_coverage_sql, build_sql, build_totals_sql, contract_text
from app.security.auth import CurrentUser
from app.sqlsafe.catalog import discover_catalog
from app.sqlsafe.executor import QueryExecutionError, audit, execute_validated
from app.sqlsafe.validator import pretty, validate_sql

log = logging.getLogger("workmate.pipeline")
MAX_STORED_ROWS = 500

STEP_NAMES = {
    1: "Schema discovery", 2: "Question interpretation", 3: "SQL generation", 4: "SQL validation",
    5: "Query execution", 6: "Result validation", 7: "Deterministic calculations", 8: "Explanation generation",
    9: "Response validation", 10: "Presentation",
}


class PipelineFailure(Exception):
    def __init__(self, status: str, code: str, message: str, step: int):
        super().__init__(message)
        self.status, self.code, self.message, self.step = status, code, message, step


class Trace:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.sql_attempts: list[dict] = []
        self._t: dict[int, float] = {}

    def start(self, n: int) -> None:
        self._t[n] = time.perf_counter()

    def done(self, n: int, status: str = "ok", detail: str | dict | None = None) -> None:
        ms = int((time.perf_counter() - self._t.get(n, time.perf_counter())) * 1000)
        self.steps.append({"step": n, "name": STEP_NAMES[n], "status": status, "duration_ms": ms, "detail": detail})

    def as_dict(self) -> dict:
        return {"steps": self.steps, "sql_attempts": self.sql_attempts}


def _campaign_names(dataset_id: int) -> list[str]:
    with app_tx() as c:
        return [r[0] for r in c.execute(
            text("SELECT campaign_name FROM analytics.campaigns WHERE dataset_id = :d ORDER BY campaign_name"),
            {"d": dataset_id})]


def _resolve(plan: QuestionPlan, anchor: date, ds: dict) -> Resolved:
    t = plan.time_range
    cur = resolve(t.preset, anchor, ds.get("first_date"), t.start, t.end)
    cmp_ = comparison_for(cur, plan.comparison) if plan.intent == "compare" else None
    notes = [f"Relative dates are anchored to the latest data date ({anchor.isoformat()})."]
    return Resolved(plan, cur, cmp_, anchor.isoformat(), notes)


# ---------------------------------------------------------------------------------- LLM steps
def _llm_interpret(provider: LLMProvider, usage: UsageTracker, question: str, catalog, anchor: date,
                   campaigns: list[str]) -> QuestionPlan:
    defs = [m.public() for m in METRICS.values()]
    user_msg = prompts.interpret_user(question, catalog.prompt_text(), defs, anchor.isoformat(), campaigns)
    feedback = None
    for attempt in range(2):
        msg = user_msg + (f"\n\nYour previous plan was invalid: {feedback}" if feedback else "")
        res = provider.complete_json(system=prompts.INTERPRET_SYSTEM, user=msg,
                                     schema=QuestionPlan.model_json_schema(), schema_name="QuestionPlan")
        usage.record("interpret", res)
        try:
            return QuestionPlan.model_validate(res.data)
        except ValidationError as e:
            feedback = "; ".join(f"{'.'.join(map(str, er['loc']))}: {er['msg']}" for er in e.errors()[:5])
            log.info("LLM plan failed validation (attempt %s): %s", attempt + 1, feedback)
    raise PipelineFailure("failed", "interpretation_failed",
                          "The question could not be interpreted into a valid analysis plan. Try rephrasing it.", 2)


def _llm_sql(provider: LLMProvider, usage: UsageTracker, question: str, plan: QuestionPlan, catalog, r: Resolved,
             feedback: str | None) -> str:
    res = provider.complete_json(
        system=prompts.SQL_SYSTEM,
        user=prompts.sql_user(question, plan.model_dump_json(), catalog.prompt_text(),
                              contract_text(r) + "\nDo not apply LIMIT or ranking; return every group.", feedback),
        schema=prompts.SQL_SCHEMA, schema_name="SqlDraft", max_tokens=1500,
    )
    usage.record("sql_generation", res)
    sql = str(res.data.get("sql", "")).strip().rstrip(";")
    if not sql:
        raise LLMError("llm_bad_output", "LLM returned an empty query.")
    return sql


def _crosscheck(r: Resolved, rows: list[dict], *, dataset_id: int, user_id: int, analysis_id: int, catalog) -> dict:
    v = validate_sql(build_totals_sql(r), catalog, 10)
    ref = execute_validated(v, dataset_id=dataset_id, source="crosscheck", user_id=user_id, analysis_id=analysis_id)
    problems = []
    for rr in ref.rows:
        period = rr["period"]
        mine = [x for x in rows if r.plan.intent != "compare" or x.get("period") == period]
        for m in BASE_MEASURES:
            a = sum(float(x[m]) for x in mine)
            b = float(rr[m] or 0)
            if abs(a - b) > max(0.005 * abs(b), 0.01):
                problems.append(f"{m} total for {period} period is {a:,.2f} but the independent check gives {b:,.2f}")
    if problems:
        raise comp.ResultValidationError(["totals do not match an independent deterministic query: " + "; ".join(problems[:3])])
    return {"matched": True, "reference_sql": v.executable_sql, "checked_measures": list(BASE_MEASURES)}


# ---------------------------------------------------------------------------------- main
def run_analysis(*, user: CurrentUser, dataset: dict, question: str, provider: LLMProvider | None,
                 parent_id: int | None = None, now: datetime | None = None) -> int:
    """Run the pipeline and persist the investigation. Returns the analysis id."""
    s = get_settings()
    mode = "llm" if provider is not None else "demo"
    usage = UsageTracker()
    trace = Trace()
    t_start = time.perf_counter()
    with app_tx() as c:
        aid = c.execute(
            text("INSERT INTO app.analyses (user_id, dataset_id, parent_id, question, title, status, mode, data_as_of)"
                 " VALUES (:u, :d, :p, :q, :t, 'running', :m, :asof) RETURNING id"),
            {"u": user.id, "d": dataset["id"], "p": parent_id, "q": question, "t": question[:120], "m": mode,
             "asof": dataset.get("last_date")},
        ).scalar()

    record: dict = {"status": "running"}
    plan: QuestionPlan | None = None
    sql_final = None
    validation = None
    try:
        # 1 ---------------------------------------------------------------- schema discovery
        trace.start(1)
        with app_tx() as c:
            catalog = discover_catalog(c)
        trace.done(1, detail={"tables": list(catalog.types), "metric_definitions": len(METRICS)})
        if dataset.get("last_date") is None:
            raise PipelineFailure("failed", "no_data", "This dataset has no rows yet. Import data first.", 1)
        anchor = anchor_date(dataset["last_date"], user.reporting_timezone, now)

        # 2 ---------------------------------------------------------------- interpretation
        trace.start(2)
        campaigns = _campaign_names(dataset["id"])
        if provider is not None:
            plan = _llm_interpret(provider, usage, question, catalog, anchor, campaigns)
        else:
            plan = demo_interpret(question, anchor, campaigns)
        trace.done(2, detail={"intent": plan.intent, "by": "llm" if provider else "rule-based demo interpreter",
                              "notes": plan.interpretation_notes})
        record["plan"] = plan.model_dump(mode="json")

        if plan.intent == "unsupported":
            raise PipelineFailure("rejected" if plan.unsafe_request else "unsupported",
                                  "unsafe_request" if plan.unsafe_request else "unsupported_question",
                                  plan.unsupported_reason or "This question can't be answered from the available data.", 2)
        if plan.intent == "ambiguous":
            raise PipelineFailure("needs_clarification", "ambiguous_question",
                                  plan.clarification_question or "Could you clarify the question?", 2)
        try:
            r = _resolve(plan, anchor, dataset)
        except PeriodError as e:
            raise PipelineFailure("needs_clarification", "invalid_time_range", str(e), 2) from e
        issue = coverage_issue(r.current, dataset.get("first_date"), dataset.get("last_date"))
        if issue and "entirely outside" in issue:
            raise PipelineFailure("needs_clarification", "no_data_in_range", issue + ". Try a range within the data.", 2)
        record["periods"] = {"current": r.current.as_dict(), "comparison": r.comparison.as_dict() if r.comparison else None,
                             "anchor_date": r.anchor, "notes": r.notes}
        limitations: list[str] = []
        if issue:
            limitations.append(issue + ".")
        if r.comparison:
            ci = coverage_issue(r.comparison, dataset.get("first_date"), dataset.get("last_date"))
            if ci:
                limitations.append(f"Comparison period: {ci}.")

        limitations.extend(_data_quality_flags(dataset["id"], r))

        if plan.intent == "anomaly_scan":
            return _anomaly_scan(aid, user, dataset, plan, r, question, mode, usage, trace, record, limitations, t_start)

        # 3-6 ------------------------------------------------------ generate, validate, execute, check
        attempts = 1 + (s.sql_repair_attempts if provider is not None else 0)
        feedback = None
        qres = None
        rows: list[dict] = []
        warnings: list[str] = []
        crosscheck = None
        for attempt in range(1, attempts + 1):
            att = {"attempt": attempt, "source": "llm" if provider else "deterministic_builder"}
            trace.sql_attempts.append(att)
            trace.start(3)
            sql = _llm_sql(provider, usage, question, plan, catalog, r, feedback) if provider else build_sql(r)
            att["sql"] = sql
            trace.done(3, detail={"attempt": attempt, "by": att["source"]})
            trace.start(4)
            validation = validate_sql(sql, catalog, s.query_row_limit)
            att["validation"] = {"ok": validation.ok, "reasons": validation.reasons}
            if not validation.ok:
                audit(source=att["source"], sql=sql, validation_ok=False, reasons=validation.reasons, executed=False,
                      user_id=user.id, analysis_id=aid, dataset_id=dataset["id"])
                trace.done(4, "failed", {"attempt": attempt, "reasons": validation.reasons})
                feedback = "SQL validation failed: " + "; ".join(validation.reasons)
                continue
            trace.done(4, detail={"attempt": attempt, "checks": len(validation.checks), "limit": validation.limit_applied})
            trace.start(5)
            try:
                qres = execute_validated(validation, dataset_id=dataset["id"], source=att["source"], user_id=user.id,
                                         analysis_id=aid)
            except QueryExecutionError as e:
                trace.done(5, "failed", {"attempt": attempt, "error": e.message})
                att["execution"] = {"ok": False, "error": e.code}
                feedback = f"Execution error: {getattr(e, 'detail', e.message)}"
                if e.code in ("query_timeout",) and provider is None:
                    raise PipelineFailure("failed", e.code, e.message, 5) from e
                continue
            trace.done(5, detail={"rows": qres.row_count, "duration_ms": qres.duration_ms, "truncated": qres.truncated})
            att["execution"] = {"ok": True, "rows": qres.row_count, "duration_ms": qres.duration_ms}
            trace.start(6)
            try:
                rows, warnings = comp.validate_rows(plan, r, qres.columns, qres.rows)
                if qres.truncated:
                    raise comp.ResultValidationError(["result exceeded the row limit; the query must aggregate further"])
                if provider is not None:
                    crosscheck = _crosscheck(r, rows, dataset_id=dataset["id"], user_id=user.id, analysis_id=aid,
                                             catalog=catalog)
            except comp.ResultValidationError as e:
                trace.done(6, "failed", {"attempt": attempt, "problems": e.problems})
                att["result_validation"] = {"ok": False, "problems": e.problems}
                feedback = "Result validation failed: " + "; ".join(e.problems)
                qres = None
                continue
            att["result_validation"] = {"ok": True}
            sql_final = sql
            break
        if qres is None:
            last = trace.sql_attempts[-1] if trace.sql_attempts else {}
            if last.get("validation", {}).get("ok") is False:
                raise PipelineFailure("failed", "sql_validation_failed",
                                      "The generated query was rejected by the SQL safety validator "
                                      f"after {attempts} attempt(s): {'; '.join(last['validation']['reasons'])}", 4)
            raise PipelineFailure("failed", "query_failed",
                                  f"The analysis query could not be completed after {attempts} attempt(s). "
                                  "Try rephrasing or narrowing the question.", 6)

        # coverage (deterministic) ------------------------------------------------------------------
        cov_v = validate_sql(build_coverage_sql(r), catalog, 5000)
        cov = execute_validated(cov_v, dataset_id=dataset["id"], source="coverage", user_id=user.id, analysis_id=aid)
        cov_notes, cov_detail = comp.coverage_limitations(cov.rows, r, dataset.get("last_date"))
        checks = {"row_count": len(rows), "warnings": warnings, "coverage": cov_detail,
                  "crosscheck": crosscheck or {"matched": None, "note": "not applicable: query built deterministically"}}
        trace.done(6, detail=checks)

        # 7 ---------------------------------------------------------------- calculations
        trace.start(7)
        calc = comp.compute(plan, r, rows)
        limitations += warnings + cov_notes + calc.pop("computed_limitations")
        if plan.intent == "compare" and plan.segment_dim():
            limitations.append("Contribution analysis shows where a change occurred, not why it occurred.")
        trace.done(7, detail={"facts": len(calc["facts"])})

        # 8-9 -------------------------------------------------------------- explanation
        explanation = _explain(provider, usage, question, plan, r, calc, limitations, trace)
        if mode == "demo":
            limitations.append("Demo mode: no LLM was called. The question was interpreted by rules and the narrative "
                               "was generated from templates; all numbers come from the database query.")
        if dataset.get("is_synthetic"):
            limitations.append("All data in this workspace is synthetic.")
        explanation["computed_limitations"] = list(dict.fromkeys(limitations))

        # 10 --------------------------------------------------------------- persist
        trace.start(10)
        result = {
            "columns": qres.columns, "rows": rows[:MAX_STORED_ROWS], "row_count": len(rows),
            "rows_stored": min(len(rows), MAX_STORED_ROWS), "query_duration_ms": qres.duration_ms,
            "periods": record["periods"], "calculations": calc, "checks": checks,
        }
        _finish(aid, status="succeeded", plan=plan, sql=sql_final, validation=validation, result=result,
                explanation=explanation, trace=trace, usage=usage, t_start=t_start, intent=plan.intent)
        return aid
    except PipelineFailure as f:
        trace.steps.append({"step": f.step, "name": STEP_NAMES[f.step], "status": "stopped", "duration_ms": 0,
                            "detail": f.message})
        extra = {"periods": record.get("periods")}
        if plan is not None and plan.intent == "ambiguous":
            extra["clarification_options"] = plan.clarification_options
        _finish(aid, status=f.status, plan=plan, sql=sql_final, validation=validation, result=extra, explanation=None,
                trace=trace, usage=usage, t_start=t_start, error=(f.code, f.message), intent=plan.intent if plan else None)
        return aid
    except LLMError as e:
        _finish(aid, status="failed", plan=plan, sql=sql_final, validation=validation, result=None, explanation=None,
                trace=trace, usage=usage, t_start=t_start, error=(e.code, e.message), intent=plan.intent if plan else None)
        return aid
    except QueryExecutionError as e:
        _finish(aid, status="failed", plan=plan, sql=sql_final, validation=validation, result=None, explanation=None,
                trace=trace, usage=usage, t_start=t_start, error=(e.code, e.message), intent=plan.intent if plan else None)
        return aid
    except Exception:
        log.exception("pipeline crashed")
        _finish(aid, status="failed", plan=plan, sql=sql_final, validation=validation, result=None, explanation=None,
                trace=trace, usage=usage, t_start=t_start,
                error=("internal_error", "The analysis failed unexpectedly. The error has been logged."),
                intent=plan.intent if plan else None)
        return aid


def _data_quality_flags(dataset_id: int, r: Resolved) -> list[str]:
    lo = min(r.current.start, r.comparison.start) if r.comparison else r.current.start
    with app_tx() as c:
        rows = c.execute(
            text("SELECT campaign_name, kind, anomaly_date, episode_end FROM app.anomalies WHERE dataset_id = :d"
                 " AND kind = 'tracking_gap' AND anomaly_date <= :e AND episode_end >= :s"
                 " ORDER BY anomaly_date"),
            {"d": dataset_id, "s": lo, "e": r.current.end},
        ).mappings().all()
    out = []
    for x in rows:
        what = "no data rows" if x["kind"] == "missing_data" else "zero conversions with normal clicks (suspected tracking gap)"
        out.append(f"Data-quality flag: '{x['campaign_name']}' had {what} from {x['anomaly_date']} to {x['episode_end']}, "
                   "inside the analysed period(s). Treat its numbers with caution.")
    return out


def _period_text(r: Resolved) -> str:
    return " ".join(p.label for p in (r.current, r.comparison) if p is not None)


def _explain(provider, usage, question, plan, r, calc, limitations, trace) -> dict:
    trace.start(8)
    source = "deterministic"
    draft = None
    violations: list[str] = []
    llm_rejections: list[list[str]] = []
    if provider is not None:
        feedback = None
        defs = [METRICS[m].public() for m in plan.metrics]
        for attempt in range(2):
            try:
                res = provider.complete_json(
                    system=prompts.EXPLAIN_SYSTEM,
                    user=prompts.explain_user(question, plan.model_dump_json(), calc["facts"], limitations, defs, feedback),
                    schema=ExplanationDraft.model_json_schema(), schema_name="ExplanationDraft", max_tokens=2000,
                )
                usage.record("explanation", res)
                d = ExplanationDraft.model_validate(res.data)
            except ValidationError as e:
                feedback = f"schema errors: {e.errors()[0]['msg']}"
                llm_rejections.append([feedback])
                continue
            out, violations = finalize(d, calc["facts"], question, "llm", _period_text(r))
            if not violations:
                trace.done(8, detail={"by": "llm", "attempts": attempt + 1})
                trace.start(9)
                trace.done(9, detail=out["verification"])
                return out
            llm_rejections.append(violations)
            feedback = "; ".join(violations[:5])
        source = "deterministic_fallback"
    draft = narrate(plan, r, calc)
    trace.done(8, detail={"by": "deterministic narrator" if source == "deterministic" else
                          "deterministic fallback (LLM draft failed verification)"})
    trace.start(9)
    out, violations = finalize(draft, calc["facts"], question, source, _period_text(r))
    if llm_rejections:
        out["verification"]["rejected_llm_drafts"] = llm_rejections
    if violations:  # should never happen for the deterministic narrator; surfaced if it does
        log.error("deterministic narrative failed verification: %s", violations)
    trace.done(9, "ok" if not violations else "failed", out["verification"])
    return out


def _anomaly_scan(aid, user, dataset, plan, r, question, mode, usage, trace, record, limitations, t_start) -> int:
    trace.start(3)
    trace.done(3, "skipped", "Answered from the statistical anomaly engine's stored detections; no SQL generated.")
    trace.start(5)
    conds = ["dataset_id = :d", "anomaly_date <= :e", "episode_end >= :s"]
    params = {"d": dataset["id"], "s": r.current.start, "e": r.current.end}
    for f in plan.filters:
        if f.dimension in ("platform", "campaign_name", "campaign_id"):
            conds.append(f"LOWER({f.dimension}) = ANY(:{f.dimension})")
            params[f.dimension] = [v.lower() for v in f.values]
    if plan.metrics:
        conds.append("(metric = ANY(:metrics) OR kind IN ('missing_data', 'tracking_gap'))")
        params["metrics"] = list(plan.metrics)
    with app_tx() as c:
        rows = [dict(x) for x in c.execute(
            text(f"SELECT * FROM app.anomalies WHERE {' AND '.join(conds)} ORDER BY anomaly_date DESC"), params
        ).mappings()]
    rows = [x for x in rows if anomaly_engine.visible(x["robust_z"], x["kind"], user.anomaly_sensitivity)]
    trace.done(5, detail={"anomalies": len(rows), "sensitivity": user.anomaly_sensitivity})
    trace.start(7)
    facts = comp.Facts()
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda x: (sev_rank[x["severity"]], -abs(x["robust_z"] or 99)))
    facts.add("anomalies.count", "Anomalies in range", float(len(rows)), str(len(rows)))
    table = []
    for x in rows:
        mk = x["metric"] if x["metric"] in METRICS else None
        fid = f"anomaly.{x['id']}"
        facts.add(f"{fid}.pct_deviation", f"{x['campaign_name']} {x['metric']} deviation", x["pct_deviation"],
                  comp.fmt_pct(x["pct_deviation"]), "calculated")
        if mk:
            facts.metric(f"{fid}.observed", f"{x['campaign_name']} {x['metric']} observed", mk, x["observed_value"])
            facts.metric(f"{fid}.expected", f"{x['campaign_name']} {x['metric']} expected", mk, x["expected_value"])
        table.append({k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in x.items()})
    trace.done(7, detail={"facts": len(facts.items)})
    trace.start(8)
    from app.pipeline.explain import Action, Statement
    obs, actions = [], []
    for x in rows[:6]:
        fid = f"anomaly.{x['id']}"
        if x["kind"] == "missing_data":
            obs.append(Statement(text=f"{x['campaign_name']}: no data rows from {x['anomaly_date']} to {x['episode_end']} "
                                      "(data completeness issue)."))
        elif x["kind"] == "tracking_gap":
            obs.append(Statement(text=f"{x['campaign_name']}: zero conversions from {x['anomaly_date']} to "
                                      f"{x['episode_end']} while clicks were normal — suspected tracking issue."))
        else:
            label = METRICS[x["metric"]].label if x["metric"] in METRICS else x["metric"]
            obs.append(Statement(text=(f"{x['campaign_name']} ({x['platform']}): {label} {x['kind']} starting "
                                       f"{x['anomaly_date']} — observed {{{{{fid}.observed}}}} vs expected "
                                       f"{{{{{fid}.expected}}}} ({{{{{fid}.pct_deviation}}}}), {x['severity']} severity.")))
    if rows:
        top = rows[0]
        summary = (f"{{{{anomalies.count}}}} anomal{'y' if len(rows) == 1 else 'ies'} detected in {r.current.label} at "
                   f"'{user.anomaly_sensitivity}' sensitivity. The most severe: {top['campaign_name']} "
                   f"({top['metric'].replace('_', ' ')}, {top['kind'].replace('_', ' ')}).")
        actions.append(Action(text="Open the Anomaly Monitor to triage each item (mark investigating, resolved or not actionable).",
                              rationale="Keeps a record of what was checked."))
        if any(x["data_quality_status"] != "ok" for x in rows):
            actions.append(Action(text="Fix data-quality items (missing rows, tracking gaps) before interpreting performance changes.",
                                  rationale="Data issues can masquerade as performance changes."))
    else:
        summary = f"No anomalies were detected in {r.current.label} at '{user.anomaly_sensitivity}' sensitivity."
    draft = ExplanationDraft(summary=summary, observed_facts=obs, recommended_actions=actions)
    trace.done(8, detail={"by": "deterministic narrator (anomaly engine)"})
    trace.start(9)
    out, _ = finalize(draft, list(facts.items.values()), question, "deterministic", _period_text(r))
    trace.done(9, detail=out["verification"])
    lim = limitations + [
        f"Detector {anomaly_engine.DETECTOR_VERSION}: robust z-score vs a 28-day day-of-week-adjusted baseline. "
        "Flags are statistical signals, not confirmed problems, and do not identify causes."]
    if dataset.get("is_synthetic"):
        lim.append("All data in this workspace is synthetic.")
    out["computed_limitations"] = lim
    result = {"periods": record["periods"], "anomalies": table, "row_count": len(table),
              "calculations": {"intent": "anomaly_scan", "facts": list(facts.items.values()), "charts": [{
                  "type": "bar", "title": "Anomalies by severity", "x_key": "label", "unit_metric": None,
                  "series": [{"key": "count", "label": "Anomalies"}],
                  "data": [{"label": s, "count": sum(1 for x in rows if x["severity"] == s)} for s in ("high", "medium", "low")],
              }]}}
    _finish(aid, status="succeeded", plan=plan, sql=None, validation=None, result=result, explanation=out, trace=trace,
            usage=usage, t_start=t_start, intent="anomaly_scan",
            sql_validation_override={"skipped": True, "reason": "answered by the anomaly engine; no SQL generated"})
    return aid


def _finish(aid, *, status, plan, sql, validation, result, explanation, trace, usage, t_start, error=None, intent=None,
            sql_validation_override=None) -> None:
    ms = int((time.perf_counter() - t_start) * 1000)
    v = sql_validation_override or (validation.as_dict() if validation is not None else None)
    with app_tx() as c:
        c.execute(
            text("""UPDATE app.analyses SET status = :status, intent = :intent, plan = CAST(:plan AS JSONB),
                    generated_sql = :sql, sql_validation = CAST(:val AS JSONB), result = CAST(:result AS JSONB),
                    explanation = CAST(:expl AS JSONB), pipeline_trace = CAST(:trace AS JSONB), error_code = :ec,
                    error_message = :em, llm_usage = CAST(:usage AS JSONB), duration_ms = :ms WHERE id = :id"""),
            {"status": status, "intent": intent, "plan": json.dumps(plan.model_dump(mode="json")) if plan else None,
             "sql": pretty(sql) if sql else None, "val": json.dumps(v, default=str) if v else None,
             "result": json.dumps(result, default=str) if result is not None else None,
             "expl": json.dumps(explanation, default=str) if explanation else None,
             "trace": json.dumps(trace.as_dict(), default=str), "ec": error[0] if error else None,
             "em": error[1] if error else None, "usage": json.dumps(usage.summary()), "ms": ms, "id": aid},
        )


def describe_value(metric: str, v) -> str:
    return format_value(metric, v)
