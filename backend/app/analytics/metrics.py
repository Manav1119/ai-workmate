"""Deterministic metric registry and calculations.

Every ratio metric is computed as a ratio of aggregate totals (e.g. SUM(conversions) /
SUM(clicks)), never as an average of daily ratios. Undefined values (zero or missing
denominators) are returned as ``None`` with an explicit reason instead of 0 or inf.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Literal

BASE_MEASURES = ("spend", "impressions", "clicks", "conversions", "revenue")
DIMENSIONS = ("campaign_id", "campaign_name", "platform", "objective", "status")


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    definition: str
    formula: str
    source_columns: tuple[str, ...]
    aggregation: Literal["sum", "ratio_of_sums"]
    unit: Literal["currency", "count", "ratio", "percent", "multiple"]
    higher_is_better: bool
    zero_handling: str
    missing_handling: str = (
        "Campaign-days with no row are treated as missing, not zero. Coverage gaps are "
        "reported as a limitation; values are never imputed."
    )
    numerator: str | None = None
    denominator: str | None = None
    min_sample: dict[str, float] = field(default_factory=dict)
    synonyms: tuple[str, ...] = ()

    def public(self) -> dict:
        d = asdict(self)
        d["source_columns"] = list(self.source_columns)
        d["synonyms"] = list(self.synonyms)
        return d


METRICS: dict[str, MetricDef] = {
    m.key: m
    for m in [
        MetricDef(
            "spend", "Spend", "Media cost in USD charged by the ad platform.", "SUM(spend)",
            ("campaign_daily_metrics.spend",), "sum", "currency", False,
            "Zero spend is a valid value.", synonyms=("cost", "budget", "ad spend", "media spend"),
        ),
        MetricDef(
            "impressions", "Impressions", "Number of times ads were shown.", "SUM(impressions)",
            ("campaign_daily_metrics.impressions",), "sum", "count", True,
            "Zero is a valid value.", synonyms=("views", "impression"),
        ),
        MetricDef(
            "clicks", "Clicks", "Link clicks reported by the platform.", "SUM(clicks)",
            ("campaign_daily_metrics.clicks",), "sum", "count", True,
            "Zero is a valid value.", synonyms=("click", "traffic"),
        ),
        MetricDef(
            "conversions", "Conversions",
            "Count of platform-attributed purchase or lead conversion events, de-duplicated at source. "
            "Exactly one row exists per campaign per reporting date (enforced by primary key), so "
            "summing rows cannot double-count a campaign-day.",
            "SUM(conversions)", ("campaign_daily_metrics.conversions",), "sum", "count", True,
            "Zero is a valid value, but zero conversions alongside normal clicks is checked as a possible tracking gap.",
            synonyms=("conversion", "purchases", "sales", "leads", "orders", "signups"),
        ),
        MetricDef(
            "revenue", "Revenue", "Platform-attributed conversion value in USD.", "SUM(revenue)",
            ("campaign_daily_metrics.revenue",), "sum", "currency", True,
            "Zero is a valid value.", synonyms=("sales value", "conversion value", "income", "gmv"),
        ),
        MetricDef(
            "ctr", "CTR", "Click-through rate: share of impressions that produced a click.",
            "SUM(clicks) / SUM(impressions)", ("campaign_daily_metrics.clicks", "campaign_daily_metrics.impressions"),
            "ratio_of_sums", "percent", True, "Undefined (null) when impressions = 0.",
            numerator="clicks", denominator="impressions", min_sample={"impressions": 1000},
            synonyms=("click-through rate", "click through rate"),
        ),
        MetricDef(
            "conversion_rate", "Conversion rate",
            "Conversions per click. Denominator is CLICKS (not sessions or impressions).",
            "SUM(conversions) / SUM(clicks)", ("campaign_daily_metrics.conversions", "campaign_daily_metrics.clicks"),
            "ratio_of_sums", "percent", True, "Undefined (null) when clicks = 0.",
            numerator="conversions", denominator="clicks", min_sample={"clicks": 200},
            synonyms=("cvr", "conversion rate", "conv rate", "cr"),
        ),
        MetricDef(
            "cpc", "CPC", "Average cost per click.", "SUM(spend) / SUM(clicks)",
            ("campaign_daily_metrics.spend", "campaign_daily_metrics.clicks"), "ratio_of_sums", "currency", False,
            "Undefined (null) when clicks = 0.", numerator="spend", denominator="clicks",
            min_sample={"clicks": 100}, synonyms=("cost per click",),
        ),
        MetricDef(
            "cpa", "CPA", "Cost per acquisition: spend divided by conversions.", "SUM(spend) / SUM(conversions)",
            ("campaign_daily_metrics.spend", "campaign_daily_metrics.conversions"), "ratio_of_sums", "currency", False,
            "Undefined (null) when conversions = 0 (reported as 'no conversions', never as 0 or infinity).",
            numerator="spend", denominator="conversions", min_sample={"conversions": 10},
            synonyms=("cost per acquisition", "cost per conversion", "cac", "cost per lead", "cpl"),
        ),
        MetricDef(
            "roas", "ROAS", "Return on ad spend: revenue divided by spend.", "SUM(revenue) / SUM(spend)",
            ("campaign_daily_metrics.revenue", "campaign_daily_metrics.spend"), "ratio_of_sums", "multiple", True,
            "Undefined (null) when spend = 0.", numerator="revenue", denominator="spend",
            min_sample={"spend": 100}, synonyms=("return on ad spend", "return on spend"),
        ),
        MetricDef(
            "aov", "AOV", "Average order value: revenue per conversion.", "SUM(revenue) / SUM(conversions)",
            ("campaign_daily_metrics.revenue", "campaign_daily_metrics.conversions"), "ratio_of_sums", "currency", True,
            "Undefined (null) when conversions = 0.", numerator="revenue", denominator="conversions",
            min_sample={"conversions": 10}, synonyms=("average order value", "order value"),
        ),
    ]
}

OVERVIEW_METRICS = ("spend", "clicks", "conversions", "revenue", "cpa", "roas")


def required_measures(metric_keys: list[str]) -> list[str]:
    """Base additive columns needed to compute the given metrics."""
    need: list[str] = []
    for k in metric_keys:
        m = METRICS[k]
        cols = [m.key] if m.aggregation == "sum" else [m.numerator, m.denominator]
        for c in cols:
            if c and c not in need:
                need.append(c)
    return need


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def compute_metric(key: str, totals: dict[str, float | None]) -> float | None:
    """Compute a metric from aggregated base-measure totals. Returns None when undefined."""
    m = METRICS[key]
    if m.aggregation == "sum":
        return _num(totals.get(key))
    num, den = _num(totals.get(m.numerator)), _num(totals.get(m.denominator))
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute_all(totals: dict[str, float | None], keys: list[str] | None = None) -> dict[str, float | None]:
    return {k: compute_metric(k, totals) for k in (keys or list(METRICS))}


@dataclass
class Change:
    current: float | None
    comparison: float | None
    abs_change: float | None
    pct_change: float | None
    note: str | None  # explains why pct_change is undefined

    def as_dict(self) -> dict:
        return asdict(self)


def pct_change(current: float | None, comparison: float | None) -> tuple[float | None, str | None]:
    """(current - comparison) / |comparison| * 100 with explicit handling of edge cases."""
    current, comparison = _num(current), _num(comparison)
    if current is None and comparison is None:
        return None, "both values missing"
    if comparison is None:
        return None, "no comparison value (missing baseline)"
    if current is None:
        return None, "no current value"
    if comparison == 0:
        if current == 0:
            return 0.0, None
        return None, "comparison value is zero; percentage change undefined"
    return (current - comparison) / abs(comparison) * 100.0, None


def change(current: float | None, comparison: float | None) -> Change:
    c, p = _num(current), _num(comparison)
    abs_c = (c - p) if (c is not None and p is not None) else None
    pct, note = pct_change(c, p)
    return Change(c, p, abs_c, pct, note)


def sample_ok(key: str, totals: dict[str, float | None]) -> tuple[bool, str | None]:
    """Check minimum sample-size requirements for a ratio metric."""
    m = METRICS[key]
    for col, minimum in m.min_sample.items():
        v = _num(totals.get(col)) or 0.0
        if v < minimum:
            return False, f"{m.label} based on only {v:,.0f} {col} (minimum {minimum:,.0f} for a reliable rate)"
    return True, None


def format_value(key: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    unit = METRICS[key].unit if key in METRICS else "count"
    if unit == "currency":
        return f"${value:,.2f}"
    if unit == "percent":
        return f"{value * 100:.2f}%"
    if unit == "multiple":
        return f"{value:.2f}x"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.4g}"


def resolve_metric(term: str) -> str | None:
    t = term.strip().lower()
    for k, m in METRICS.items():
        if t == k or t == m.label.lower() or t in m.synonyms:
            return k
    return None
