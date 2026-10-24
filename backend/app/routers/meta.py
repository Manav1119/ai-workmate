"""Health, system status, schema and metric definitions, overview metrics."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.analytics import anomalies as anomaly_engine
from app.analytics.metrics import BASE_MEASURES, METRICS, OVERVIEW_METRICS, change, compute_metric, format_value
from app.analytics.periods import anchor_date, comparison_for, resolve
from app.config import get_settings
from app.connectors.base import list_connectors
from app.db import app_tx, ping
from app.pipeline.compute import fmt_delta, fmt_pct
from app.security.auth import CurrentUser, current_user, dataset_for_user
from app.services.datasets import freshness
from app.sqlsafe.catalog import discover_catalog

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    db = ping()
    ok = all(db.values())
    return {"status": "ok" if ok else "degraded", **db, "llm_mode": "llm" if get_settings().llm_enabled else "demo"}


@router.get("/api/system/status")
def system_status(user: CurrentUser = Depends(current_user)) -> dict:
    s = get_settings()
    return {
        "mode": "llm" if s.llm_enabled else "demo",
        "llm_provider": s.llm_provider if s.llm_enabled else None,
        "llm_model": s.resolved_llm_model if s.llm_enabled else None,
        "llm_key_configured": s.llm_enabled,
        "query_timeout_ms": s.query_timeout_ms,
        "query_row_limit": s.query_row_limit,
        "sql_repair_attempts": s.sql_repair_attempts,
        "analysis_rate_limit_per_minute": s.analysis_rate_limit_per_minute,
        "upload_max_mb": s.upload_max_bytes // (1024 * 1024),
        "upload_max_rows": s.upload_max_rows,
        "anomaly_detector": anomaly_engine.DETECTOR_VERSION,
        "sensitivity_thresholds": anomaly_engine.SENSITIVITY_Z,
        "connectors": list_connectors(),
    }


@router.get("/api/schema")
def schema(user: CurrentUser = Depends(current_user)) -> dict:
    with app_tx() as c:
        return discover_catalog(c).describe()


@router.get("/api/metric-definitions")
def metric_definitions() -> dict:
    return {"metrics": [m.public() for m in METRICS.values()]}


@router.get("/api/metrics/overview")
def overview(
    dataset_id: int | None = None,
    days: int = Query(7, ge=1, le=90),
    series_days: int = Query(60, ge=7, le=365),
    user: CurrentUser = Depends(current_user),
) -> dict:
    ds = dataset_for_user(user, dataset_id)
    fr = freshness(ds, user.reporting_timezone)
    base = {"user": {"display_name": user.display_name, "is_demo": user.is_demo},
            "dataset": {"id": ds["id"], "name": ds["name"], "is_synthetic": ds["is_synthetic"], "kind": ds["kind"]},
            "freshness": fr}
    if ds["last_date"] is None:
        return {**base, "empty": True, "kpis": [], "series": [], "anomalies": [], "recent_investigations": []}
    anchor = anchor_date(ds["last_date"], user.reporting_timezone)
    cur = resolve(f"last_{days}_days" if days in (7, 14, 28, 30, 90) else "custom", anchor,
                  start=anchor - timedelta(days=days - 1), end=anchor)
    prev = comparison_for(cur, "previous_period")
    sums = ", ".join(f"COALESCE(SUM({m}), 0)::float AS {m}" for m in BASE_MEASURES)
    with app_tx() as c:
        q = text(f"SELECT {sums} FROM analytics.campaign_daily_metrics WHERE dataset_id = :d AND date BETWEEN :s AND :e")
        t1 = dict(c.execute(q, {"d": ds["id"], "s": cur.start, "e": cur.end}).mappings().one())
        t0 = dict(c.execute(q, {"d": ds["id"], "s": prev.start, "e": prev.end}).mappings().one())
        series_rows = c.execute(
            text(f"SELECT date, {sums} FROM analytics.campaign_daily_metrics WHERE dataset_id = :d AND date > :s"
                 " AND date <= :e GROUP BY date ORDER BY date"),
            {"d": ds["id"], "s": anchor - timedelta(days=series_days), "e": anchor},
        ).mappings().all()
        anoms = [dict(x) for x in c.execute(
            text("SELECT a.*, COALESCE(st.status, 'new') AS status FROM app.anomalies a LEFT JOIN app.anomaly_states st"
                 " ON st.anomaly_id = a.id AND st.user_id = :u WHERE a.dataset_id = :d AND a.episode_end >= :since"
                 " ORDER BY CASE a.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.anomaly_date DESC"),
            {"u": user.id, "d": ds["id"], "since": anchor - timedelta(days=28)},
        ).mappings()]
        recent = c.execute(
            text("SELECT id, question, status, mode, created_at, saved FROM app.analyses WHERE user_id = :u"
                 " ORDER BY created_at DESC LIMIT 5"), {"u": user.id},
        ).mappings().all()
    kpis = []
    for m in OVERVIEW_METRICS:
        ch = change(compute_metric(m, t1), compute_metric(m, t0))
        kpis.append({"metric": m, "label": METRICS[m].label, "unit": METRICS[m].unit,
                     "higher_is_better": METRICS[m].higher_is_better, **ch.as_dict(),
                     "current_display": format_value(m, ch.current), "comparison_display": format_value(m, ch.comparison),
                     "abs_change_display": fmt_delta(m, ch.abs_change), "pct_change_display": fmt_pct(ch.pct_change)})
    series = []
    for r in series_rows:
        t = dict(r)
        series.append({"date": t["date"].isoformat(), **{m: t[m] for m in BASE_MEASURES},
                       "cpa": compute_metric("cpa", t), "roas": compute_metric("roas", t),
                       "conversion_rate": compute_metric("conversion_rate", t)})
    anoms = [a for a in anoms if anomaly_engine.visible(a["robust_z"], a["kind"], user.anomaly_sensitivity)
             and a["status"] in ("new", "investigating")]
    return {
        **base, "empty": False, "anchor_date": anchor.isoformat(),
        "period": cur.as_dict(), "comparison": prev.as_dict(), "kpis": kpis, "series": series,
        "anomalies": [_anom_out(a) for a in anoms[:6]], "anomalies_open_count": len(anoms),
        "recent_investigations": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in recent],
    }


def _anom_out(a: dict) -> dict:
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in a.items()}
    m = a["metric"]
    if m in METRICS:
        out["observed_display"] = format_value(m, a["observed_value"])
        out["expected_display"] = format_value(m, a["expected_value"])
        out["expected_range_display"] = (f"{format_value(m, a['expected_low'])} – {format_value(m, a['expected_high'])}"
                                         if a.get("expected_low") is not None else None)
        out["metric_label"] = METRICS[m].label
    else:
        out["observed_display"] = f"{a['observed_value']:.0f} rows" if a["observed_value"] is not None else "n/a"
        out["expected_display"] = (f"{a['expected_value']:.0f} rows" if a["kind"] == "missing_data"
                                   else str(a["expected_value"]))
        out["expected_range_display"] = None
        out["metric_label"] = "Data completeness"
    if a["kind"] == "tracking_gap":
        out["observed_display"] = "0 conversions"
        out["expected_display"] = f"~{a['expected_value']:.0f} conversions/day"
    out["pct_deviation_display"] = fmt_pct(a["pct_deviation"])
    return out
