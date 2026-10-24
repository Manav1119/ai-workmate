"""User-triggered daily briefing (deterministic). No scheduler in v1 by design."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from app.analytics import anomalies as anomaly_engine
from app.analytics.metrics import METRICS, change, compute_metric, format_value
from app.analytics.periods import anchor_date, comparison_for, resolve
from app.db import app_tx
from app.pipeline.compute import fmt_pct
from app.services.datasets import freshness

KPIS = ["spend", "conversions", "revenue", "conversion_rate", "cpa", "roas"]
SIGNIFICANT_PCT = 10.0


def _totals(c, dataset_id: int, start, end) -> dict:
    r = c.execute(
        text("SELECT COALESCE(SUM(spend),0)::float spend, COALESCE(SUM(impressions),0)::float impressions,"
             " COALESCE(SUM(clicks),0)::float clicks, COALESCE(SUM(conversions),0)::float conversions,"
             " COALESCE(SUM(revenue),0)::float revenue FROM analytics.campaign_daily_metrics"
             " WHERE dataset_id = :d AND date BETWEEN :s AND :e"),
        {"d": dataset_id, "s": start, "e": end},
    ).mappings().one()
    return dict(r)


def build_briefing(user, ds: dict, now: datetime | None = None) -> dict:
    anchor = anchor_date(ds["last_date"], user.reporting_timezone, now)
    cur = resolve("last_7_days", anchor)
    prev = comparison_for(cur, "previous_period")
    with app_tx() as c:
        t1, t0 = _totals(c, ds["id"], cur.start, cur.end), _totals(c, ds["id"], prev.start, prev.end)
        anoms = [dict(x) for x in c.execute(
            text("SELECT a.*, COALESCE(s.status, 'new') AS status FROM app.anomalies a"
                 " LEFT JOIN app.anomaly_states s ON s.anomaly_id = a.id AND s.user_id = :u"
                 " WHERE a.dataset_id = :d AND a.episode_end >= :since ORDER BY a.anomaly_date DESC"),
            {"u": user.id, "d": ds["id"], "since": cur.start},
        ).mappings()]
        unresolved_inv = [dict(x) for x in c.execute(
            text("SELECT id, question, status, created_at FROM app.analyses WHERE user_id = :u AND dataset_id = :d AND"
                 " status IN ('failed', 'needs_clarification') ORDER BY created_at DESC LIMIT 5"),
            {"u": user.id, "d": ds["id"]},
        ).mappings()]
        investigating = c.execute(
            text("SELECT COUNT(*) FROM app.anomaly_states s JOIN app.anomalies a ON a.id = s.anomaly_id"
                 " WHERE s.user_id = :u AND a.dataset_id = :d AND s.status = 'investigating'"),
            {"u": user.id, "d": ds["id"]},
        ).scalar()
    anoms = [a for a in anoms if anomaly_engine.visible(a["robust_z"], a["kind"], user.anomaly_sensitivity)]
    changes = []
    for m in KPIS:
        ch = change(compute_metric(m, t1), compute_metric(m, t0))
        changes.append({"metric": m, "label": METRICS[m].label, "current": format_value(m, ch.current),
                        "comparison": format_value(m, ch.comparison), "pct_change": ch.pct_change,
                        "pct_change_display": fmt_pct(ch.pct_change),
                        "significant": ch.pct_change is not None and abs(ch.pct_change) >= SIGNIFICANT_PCT,
                        "good": None if ch.pct_change is None else ((ch.pct_change > 0) == METRICS[m].higher_is_better)})
    new_anoms = [a for a in anoms if a["status"] == "new"]
    by_campaign: dict[str, list] = {}
    for a in new_anoms:
        by_campaign.setdefault(a["campaign_name"], []).append(a)
    need = sorted(by_campaign.items(), key=lambda kv: (-sum(1 for a in kv[1] if a["severity"] == "high"), -len(kv[1])))
    fr = freshness(ds, user.reporting_timezone, now)
    dq = [a for a in anoms if a["kind"] in ("missing_data", "tracking_gap")]
    lines = [f"# Daily briefing — {anchor.isoformat()}", "",
             f"_Data through {fr['last_data_date']} ({fr['days_since_last_data']} day(s) ago, {fr['status']}). "
             f"Last 7 days vs previous 7 days. Generated deterministically; no LLM call._", ""]
    if ds.get("is_synthetic"):
        lines += ["_All figures come from the SYNTHETIC demo dataset._", ""]
    lines += ["## Significant metric changes", ""]
    sig = [x for x in changes if x["significant"]]
    lines += ([f"- **{x['label']}**: {x['comparison']} → {x['current']} ({x['pct_change_display']})" for x in sig]
              or ["- No KPI moved by 10% or more."])
    lines += ["", "## New anomalies", ""]
    lines += ([f"- {a['campaign_name']} — {a['metric'].replace('_', ' ')} {a['kind'].replace('_', ' ')} from "
               f"{a['anomaly_date']} ({a['severity']})" for a in new_anoms[:8]] or ["- None in the last 7 days."])
    lines += ["", "## Data freshness and quality", ""]
    fresh_line = (f"- Latest data is {fr['days_since_last_data']} day(s) old ({fr['status']})."
                  if fr["days_since_last_data"] is not None else "- No data loaded.")
    lines.append(fresh_line)
    lines += [f"- {a['campaign_name']}: {a['kind'].replace('_', ' ')} {a['anomaly_date']} → {a['episode_end']}" for a in dq]
    lines += ["", "## Campaigns needing investigation", ""]
    lines += ([f"- {name}: {len(items)} new anomal{'y' if len(items) == 1 else 'ies'} "
               f"({', '.join(sorted({i['metric'].replace('_', ' ') for i in items}))})" for name, items in need[:5]]
              or ["- Nothing flagged."])
    lines += ["", "## Open items", "",
              f"- Anomalies you marked 'investigating': {investigating}",
              f"- Investigations that failed or need clarification: {len(unresolved_inv)}"]
    lines += [f"  - #{x['id']}: {x['question']} ({x['status']})" for x in unresolved_inv]
    return {
        "anchor_date": anchor.isoformat(), "period": cur.as_dict(), "comparison": prev.as_dict(), "freshness": fr,
        "changes": changes, "new_anomalies": len(new_anoms), "data_quality_issues": len(dq),
        "campaigns_needing_investigation": [{"campaign_name": n, "count": len(i)} for n, i in need[:5]],
        "investigating_anomalies": int(investigating or 0), "unresolved_investigations": unresolved_inv,
        "markdown": "\n".join(lines) + "\n", "generated_by": "deterministic",
    }
