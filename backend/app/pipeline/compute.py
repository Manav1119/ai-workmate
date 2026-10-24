"""Step 6 + 7: result validation and deterministic calculations.

Turns validated query rows into: key metrics, segment contributions, series, facts
(the only numbers the explanation may cite), chart specs and computed limitations.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from app.analytics.contribution import contributions
from app.analytics.metrics import BASE_MEASURES, METRICS, change, compute_metric, format_value, sample_ok
from app.pipeline.plan import QuestionPlan
from app.pipeline.sqlbuild import Resolved, contract_columns

CONTEXT_METRICS = ["spend", "clicks", "conversions", "revenue", "conversion_rate", "cpa", "roas"]


class ResultValidationError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def slug(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(v).lower()).strip("_")[:40] or "x"


def fmt_pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "n/a"
    if not signed:
        return f"{v:.1f}%"
    return f"{v:+.1f}%".replace("-", "−")


def fmt_delta(metric: str, v: float | None) -> str:
    if v is None:
        return "n/a"
    unit = METRICS[metric].unit
    sign = "+" if v > 0 else ("−" if v < 0 else "±")
    a = abs(v)
    if unit == "currency":
        return f"{sign}${a:,.2f}"
    if unit == "percent":
        return f"{sign}{a * 100:.2f} pp"
    if unit == "multiple":
        return f"{sign}{a:.2f}x"
    return f"{sign}{a:,.0f}"


class Facts:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, fid: str, label: str, value: float | None, display: str, kind: str = "observed") -> str:
        self.items[fid] = {"id": fid, "label": label, "value": value, "display": display, "kind": kind}
        return fid

    def metric(self, fid: str, label: str, metric: str, value: float | None, kind: str = "observed") -> str:
        return self.add(fid, label, value, format_value(metric, value), kind)


# --------------------------------------------------------------------------- validation
def validate_rows(plan: QuestionPlan, r: Resolved, columns: list[str], rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Normalise and validate query output against the result contract."""
    problems: list[str] = []
    warnings: list[str] = []
    cols = [c.lower() for c in columns]
    need = contract_columns(plan)
    missing = [c for c in need if c not in cols]
    if missing:
        raise ResultValidationError([f"result is missing required column(s): {', '.join(missing)}"])
    norm: list[dict] = []
    null_cells = 0
    for row in rows:
        row = {k.lower(): v for k, v in row.items()}
        for m in BASE_MEASURES:
            v = row.get(m)
            if v is None:
                null_cells += 1
                v = 0.0
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ResultValidationError([f"non-numeric value in column {m}"]) from None
            if v < 0:
                problems.append(f"negative value in column {m}")
            row[m] = v
        norm.append(row)
    if null_cells:
        warnings.append(f"{null_cells} null measure value(s) in the result were treated as 0.")
    if plan.intent == "compare":
        bad = {str(r_.get("period")) for r_ in norm} - {"current", "comparison"}
        if bad:
            problems.append(f"unexpected period label(s): {', '.join(sorted(bad))}")
    if plan.intent == "trend":
        for row in norm:
            try:
                d = date.fromisoformat(str(row["date"])[:10])
            except ValueError:
                problems.append("date column contains non-date values")
                break
            lo = r.current.start - timedelta(days=6) if "week" in plan.group_by else r.current.start
            if d < lo or d > r.current.end:
                problems.append(f"date {d} is outside the requested range {r.current.start}..{r.current.end}")
                break
            row["date"] = d.isoformat()
    key_cols = [c for c in need if c not in BASE_MEASURES and c != "campaign_name"]
    seen: set[tuple] = set()
    for row in norm:
        k = tuple(str(row.get(c)) for c in key_cols)
        if k in seen:
            problems.append(f"duplicate result rows for {dict(zip(key_cols, k))} (possible double counting)")
            break
        seen.add(k)
    if plan.intent == "aggregate" and len(norm) > 1:
        problems.append("aggregate query returned more than one row")
    if problems:
        raise ResultValidationError(problems)
    return norm, warnings


def totals_by(rows: list[dict], key: str | None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: {m: 0.0 for m in BASE_MEASURES})
    for row in rows:
        k = str(row.get(key)) if key else "all"
        for m in BASE_MEASURES:
            out[k][m] += row[m]
    return dict(out)


def coverage_limitations(cov_rows: list[dict], r: Resolved, last_data: date | None) -> tuple[list[str], dict]:
    notes: list[str] = []
    detail: dict = {"campaigns": []}
    for row in cov_rows:
        first = date.fromisoformat(str(row["first_date"])[:10])
        last = date.fromisoformat(str(row["last_date"])[:10])
        active_end = (last_data or last) if row.get("status") == "active" else last
        for label, period, present in (
            ("current", r.current, int(row["current_days"])),
            ("comparison", r.comparison, int(row.get("comparison_days") or 0)),
        ):
            if period is None:
                continue
            s, e = max(period.start, first), min(period.end, active_end)
            expected = max(0, (e - s).days + 1)
            if expected > present:
                miss = expected - present
                detail["campaigns"].append(
                    {"campaign_id": row["campaign_id"], "campaign_name": row["campaign_name"], "period": label,
                     "expected_days": expected, "present_days": present}
                )
                notes.append(
                    f"Missing data: '{row['campaign_name']}' has {miss} of {expected} expected day(s) without rows in "
                    f"the {label} period. Totals are understated for those days; values were not imputed."
                )
    return notes, detail


# --------------------------------------------------------------------------- calculations
def compute(plan: QuestionPlan, r: Resolved, rows: list[dict]) -> dict:
    facts = Facts()
    limitations: list[str] = []
    charts: list[dict] = []
    out: dict = {"intent": plan.intent, "primary_metric": plan.primary_metric}
    seg = plan.segment_dim()
    seg_key = {"campaign": "campaign_id", "platform": "platform", "objective": "objective"}.get(seg or "")
    labels: dict[str, str] = {}
    if seg_key:
        for row in rows:
            labels[str(row.get(seg_key))] = str(row.get("campaign_name") or row.get(seg_key))
    metrics_shown = list(dict.fromkeys([*plan.metrics, *CONTEXT_METRICS]))
    pm = plan.primary_metric

    if plan.intent == "compare":
        cur_rows = [x for x in rows if x.get("period") == "current"]
        cmp_rows = [x for x in rows if x.get("period") == "comparison"]
        t1 = totals_by(cur_rows, None).get("all", {m: 0.0 for m in BASE_MEASURES})
        t0 = totals_by(cmp_rows, None).get("all", {m: 0.0 for m in BASE_MEASURES})
        if not cur_rows and not cmp_rows:
            limitations.append("No rows matched the question's filters in either period.")
        key_metrics = []
        for m in metrics_shown:
            ch = change(compute_metric(m, t1), compute_metric(m, t0))
            lbl = METRICS[m].label
            facts.metric(f"total.{m}.current", f"{lbl}, {r.current.label}", m, ch.current)
            facts.metric(f"total.{m}.comparison", f"{lbl}, {r.comparison.label}", m, ch.comparison)
            facts.add(f"total.{m}.abs_change", f"{lbl} absolute change", ch.abs_change, fmt_delta(m, ch.abs_change), "calculated")
            facts.add(f"total.{m}.pct_change", f"{lbl} % change", ch.pct_change, fmt_pct(ch.pct_change), "calculated")
            key_metrics.append({"metric": m, "label": lbl, "requested": m in plan.metrics, **ch.as_dict(),
                                "current_display": format_value(m, ch.current),
                                "comparison_display": format_value(m, ch.comparison),
                                "abs_change_display": fmt_delta(m, ch.abs_change),
                                "pct_change_display": fmt_pct(ch.pct_change),
                                "higher_is_better": METRICS[m].higher_is_better})
            if ch.note and m in plan.metrics:
                limitations.append(f"{lbl}: {ch.note}.")
            if METRICS[m].aggregation == "ratio_of_sums" and m in plan.metrics:
                for tot, per in ((t1, "current"), (t0, "comparison")):
                    ok, why = sample_ok(m, tot)
                    if not ok:
                        limitations.append(f"Small sample in the {per} period: {why}.")
        out["key_metrics"] = key_metrics
        out["totals"] = {"current": t1, "comparison": t0}
        if seg_key:
            c1, c0 = totals_by(cur_rows, seg_key), totals_by(cmp_rows, seg_key)
            contrib_out = {}
            for m in plan.metrics[:3]:
                cr = contributions(m, c1, c0, labels)
                contrib_out[m] = cr.as_dict()
                limitations.extend(n for n in cr.notes if n not in limitations)
                for s in cr.segments:
                    sid = slug(s.segment)
                    facts.add(f"seg.{sid}.{m}.contribution", f"{s.label}: contribution to {METRICS[m].label} change",
                              s.contribution, fmt_delta(m, s.contribution), "calculated")
                    facts.metric(f"seg.{sid}.{m}.current", f"{s.label}: {METRICS[m].label}, current", m, s.current)
                    facts.metric(f"seg.{sid}.{m}.comparison", f"{s.label}: {METRICS[m].label}, comparison", m, s.comparison)
                    facts.add(f"seg.{sid}.{m}.pct_change", f"{s.label}: {METRICS[m].label} % change", s.pct_change,
                              fmt_pct(s.pct_change), "calculated")
                    if s.share_of_change is not None:
                        facts.add(f"seg.{sid}.{m}.share_of_change", f"{s.label}: share of total {METRICS[m].label} change",
                                  s.share_of_change * 100, fmt_pct(s.share_of_change * 100, signed=False), "calculated")
            out["contributions"] = contrib_out
            # context for the largest contributors (traffic vs. efficiency), used by the narrative
            if pm in contrib_out:
                top3 = sorted(contrib_out[pm]["segments"], key=lambda s: -abs(s["contribution"]))[:3]
                ctx = []
                for s in top3:
                    sid = slug(s["segment"])
                    a, b = c1.get(s["segment"], {}), c0.get(s["segment"], {})
                    item = {"segment": s["segment"], "label": s["label"], "metrics": {}}
                    for m in ("clicks", "spend", "conversions", "revenue", "conversion_rate", "cpa", "roas"):
                        ch = change(compute_metric(m, a) if a else None, compute_metric(m, b) if b else None)
                        item["metrics"][m] = ch.as_dict()
                        if f"seg.{sid}.{m}.current" not in facts.items:
                            facts.metric(f"seg.{sid}.{m}.current", f"{s['label']}: {METRICS[m].label}, current", m, ch.current)
                            facts.metric(f"seg.{sid}.{m}.comparison", f"{s['label']}: {METRICS[m].label}, comparison", m,
                                         ch.comparison)
                            facts.add(f"seg.{sid}.{m}.pct_change", f"{s['label']}: {METRICS[m].label} % change",
                                      ch.pct_change, fmt_pct(ch.pct_change), "calculated")
                    ctx.append(item)
                out["top_segment_context"] = ctx
            if pm in contrib_out and contrib_out[pm]["segments"]:
                segs = contrib_out[pm]["segments"]
                top = sorted(segs, key=lambda s: -abs(s["contribution"]))[:10]
                charts.append({
                    "type": "bar", "title": f"Contribution to {METRICS[pm].label} change by {seg}",
                    "x_key": "label", "unit_metric": pm, "diverging": True,
                    "series": [{"key": "contribution", "label": "Contribution"}],
                    "data": [{"label": s["label"], "contribution": s["contribution"]} for s in top],
                })
                charts.append({
                    "type": "grouped_bar", "title": f"{METRICS[pm].label}: {r.current.label} vs {r.comparison.label}",
                    "x_key": "label", "unit_metric": pm,
                    "series": [{"key": "comparison", "label": "Comparison"}, {"key": "current", "label": "Current"}],
                    "data": [{"label": s["label"],
                              "current": compute_metric(pm, c1.get(s["segment"], {})) if s["segment"] in c1 else None,
                              "comparison": compute_metric(pm, c0.get(s["segment"], {})) if s["segment"] in c0 else None}
                             for s in top],
                })
        else:
            charts.append({
                "type": "grouped_bar", "title": f"{METRICS[pm].label}: current vs comparison", "x_key": "label",
                "unit_metric": pm, "series": [{"key": "value", "label": METRICS[pm].label}],
                "data": [{"label": r.comparison.label, "value": compute_metric(pm, t0)},
                         {"label": r.current.label, "value": compute_metric(pm, t1)}],
            })

    elif plan.intent == "trend":
        by_date = totals_by(rows, "date")
        dates = sorted(by_date)
        series = []
        for d in dates:
            pt = {"date": d}
            for m in plan.metrics:
                pt[m] = compute_metric(m, by_date[d])
            series.append(pt)
        out["series"] = series
        tot = totals_by(rows, None).get("all", {x: 0.0 for x in BASE_MEASURES})
        weekly = "week" in plan.group_by
        if not weekly:
            have = {date.fromisoformat(d) for d in dates}
            exp_days = {r.current.start + timedelta(days=i) for i in range(r.current.days)}
            gaps = sorted(exp_days - have)
            if gaps:
                limitations.append(f"{len(gaps)} day(s) in the range have no data at all (e.g. {gaps[0]}).")
        summary = []
        for m in plan.metrics:
            lbl = METRICS[m].label
            overall = compute_metric(m, tot)
            facts.metric(f"trend.{m}.overall", f"{lbl} over {r.current.label} (ratio of totals)" if
                         METRICS[m].aggregation != "sum" else f"{lbl} total over {r.current.label}", m, overall)
            vals = [(p["date"], p[m]) for p in series if p[m] is not None]
            item = {"metric": m, "label": lbl, "overall": overall, "overall_display": format_value(m, overall)}
            if vals:
                hi = max(vals, key=lambda x: x[1])
                lo = min(vals, key=lambda x: x[1])
                facts.metric(f"trend.{m}.max", f"Highest {lbl} ({hi[0]})", m, hi[1])
                facts.metric(f"trend.{m}.min", f"Lowest {lbl} ({lo[0]})", m, lo[1])
                item.update(max={"date": hi[0], "value": hi[1]}, min={"date": lo[0], "value": lo[1]})
                n = 1 if weekly else 7
                if len(dates) >= 2 * n:
                    first = {x: sum(by_date[d][x] for d in dates[:n]) for x in BASE_MEASURES}
                    last = {x: sum(by_date[d][x] for d in dates[-n:]) for x in BASE_MEASURES}
                    ch = change(compute_metric(m, last), compute_metric(m, first))
                    span = "week" if weekly else "7 days"
                    facts.metric(f"trend.{m}.first_window", f"{lbl}, first {span} of range", m, ch.comparison)
                    facts.metric(f"trend.{m}.last_window", f"{lbl}, last {span} of range", m, ch.current)
                    facts.add(f"trend.{m}.window_pct_change", f"{lbl}: last vs first {span} % change", ch.pct_change,
                              fmt_pct(ch.pct_change), "calculated")
                    item["first_vs_last"] = ch.as_dict()
            summary.append(item)
        out["trend_summary"] = summary
        out["totals"] = {"current": tot}
        charts.append({
            "type": "line", "title": f"{', '.join(METRICS[m].label for m in plan.metrics[:2])} — "
                                     f"{'weekly' if weekly else 'daily'}, {r.current.label}",
            "x_key": "date", "unit_metric": pm,
            "series": [{"key": m, "label": METRICS[m].label, "unit_metric": m} for m in plan.metrics[:2]],
            "data": series,
        })

    elif plan.intent in ("breakdown", "aggregate"):
        tot = totals_by(rows, None).get("all", {x: 0.0 for x in BASE_MEASURES})
        out["totals"] = {"current": tot}
        key_metrics = []
        for m in metrics_shown:
            v = compute_metric(m, tot)
            facts.metric(f"total.{m}.current", f"{METRICS[m].label}, {r.current.label}", m, v)
            key_metrics.append({"metric": m, "label": METRICS[m].label, "requested": m in plan.metrics, "current": v,
                                "current_display": format_value(m, v)})
            if METRICS[m].aggregation == "ratio_of_sums" and m in plan.metrics:
                ok, why = sample_ok(m, tot)
                if not ok:
                    limitations.append(f"Small sample: {why}.")
        out["key_metrics"] = key_metrics
        if plan.intent == "breakdown" and seg_key:
            per = totals_by(rows, seg_key)
            table = []
            for k, t in per.items():
                rowm = {"segment": k, "label": labels.get(k, k)}
                for m in metrics_shown:
                    rowm[m] = compute_metric(m, t)
                for b in BASE_MEASURES:
                    rowm[f"share_{b}"] = (t[b] / tot[b] * 100) if tot[b] else None
                low = [m for m in plan.metrics if METRICS[m].aggregation == "ratio_of_sums" and not sample_ok(m, t)[0]]
                rowm["low_sample_metrics"] = low
                table.append(rowm)
            order = plan.ranking.order if plan.ranking else ("asc" if not METRICS[pm].higher_is_better else "desc")
            table.sort(key=lambda x: (x[pm] is None, -(x[pm] or 0) if order == "desc" else (x[pm] or 0)))
            if plan.highlight == "high_cost_low_efficiency":
                spends = sorted(x["spend"] or 0 for x in table)
                med = spends[len(spends) // 2] if spends else 0
                eff = pm if METRICS[pm].aggregation == "ratio_of_sums" else "conversion_rate"
                overall_eff = compute_metric(eff, tot)
                for x in table:
                    v = x.get(eff)
                    worse = (v is not None and overall_eff is not None and
                             (v < overall_eff if METRICS[eff].higher_is_better else v > overall_eff))
                    x["flagged"] = bool((x["spend"] or 0) >= med and worse and eff not in x["low_sample_metrics"])
                out["highlight_rule"] = (
                    f"Flagged = spend at or above the median segment spend ({format_value('spend', med)}) AND "
                    f"{METRICS[eff].label} worse than the overall {format_value(eff, overall_eff)}; low-sample segments excluded."
                )
                facts.metric("rule.median_spend", "Median segment spend", "spend", med, "calculated")
                facts.metric(f"rule.overall_{eff}", f"Overall {METRICS[eff].label}", eff, overall_eff, "calculated")
            if plan.ranking:
                table = table[: plan.ranking.limit]
            for i, x in enumerate(table):
                sid = slug(x["segment"])
                for m in plan.metrics:
                    facts.metric(f"seg.{sid}.{m}.value", f"{x['label']}: {METRICS[m].label}", m, x[m])
                facts.add(f"seg.{sid}.spend.share", f"{x['label']}: share of spend", x["share_spend"],
                          fmt_pct(x["share_spend"], signed=False), "calculated")
                x["rank"] = i + 1
            out["breakdown"] = table
            lowsamp = [x["label"] for x in table if x["low_sample_metrics"]]
            if lowsamp:
                limitations.append("Low sample size (rates are noisy) for: " + ", ".join(lowsamp[:6]) + ".")
            charts.append({
                "type": "bar", "title": f"{METRICS[pm].label} by {seg}, {r.current.label}", "x_key": "label",
                "unit_metric": pm, "series": [{"key": pm, "label": METRICS[pm].label}],
                "highlight_key": "flagged" if plan.highlight != "none" else None,
                "data": [{"label": x["label"], pm: x[pm], "flagged": x.get("flagged", False)} for x in table[:15]],
            })
            if plan.highlight != "none" and "spend" in plan.metrics:
                charts.append({
                    "type": "bar", "title": f"Spend by {seg}, {r.current.label}", "x_key": "label",
                    "unit_metric": "spend", "series": [{"key": "spend", "label": "Spend"}],
                    "highlight_key": "flagged",
                    "data": [{"label": x["label"], "spend": x["spend"], "flagged": x.get("flagged", False)} for x in table[:15]],
                })
    out["facts"] = list(facts.items.values())
    out["charts"] = charts
    out["computed_limitations"] = limitations
    return out
