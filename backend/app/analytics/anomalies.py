"""Statistical anomaly detection (no ML).

Method (detector version ``robust-dow-v1``), per campaign and metric:

* Baseline = the previous 28 days *that have data* (missing days are never imputed).
* Seasonality: additive metrics are de-seasonalised with day-of-week factors estimated
  on the previous 56 days, so normal weekend dips are not flagged.
* Expected value = median of the de-seasonalised baseline x today's weekday factor.
  Ratio metrics use the ratio of baseline sums (never an average of daily ratios).
* Spread = robust (MAD x 1.4826), floored by a sampling-noise term (Poisson for counts,
  binomial for conversion rate) and 3% of the level, so tiny campaigns don't explode.
* A day is anomalous only if |robust z| >= threshold AND |deviation| >= 20% AND the
  minimum sample size for the metric is met. Consecutive anomalous days are merged
  into one episode.
* Data-quality checks run first: missing campaign-days (active campaigns only) and
  tracking gaps (zero conversions while clicks are normal and >= 8 conversions expected).
  Tracking-gap days are excluded from conversion-based detection and baselines.

Anomalies are stored at the most sensitive threshold; each user's sensitivity setting
filters what is shown. Detection never asserts a cause.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

DETECTOR_VERSION = "robust-dow-v1"
SENSITIVITY_Z = {"conservative": 5.0, "balanced": 4.0, "sensitive": 3.0}
STORE_Z = min(SENSITIVITY_Z.values())
MIN_REL_DEVIATION = 0.20
BASELINE_DAYS = 28
SEASONAL_DAYS = 56
MIN_BASELINE_POINTS = 21

ADDITIVE = {"spend": 50.0, "clicks": 50.0, "conversions": 5.0, "revenue": 200.0}  # min expected level
RATIOS = {
    # metric: (numerator, denominator, min denominator on the day)
    "conversion_rate": ("conversions", "clicks", 200.0),
    "cpa": ("spend", "conversions", 10.0),
    "roas": ("revenue", "spend", 100.0),
}
CONVERSION_BASED = {"conversions", "revenue", "conversion_rate", "cpa", "roas"}


@dataclass
class Detection:
    metric: str
    campaign_id: str
    campaign_name: str
    platform: str
    anomaly_date: date
    episode_end: date
    episode_days: int
    kind: str
    observed_value: float | None
    expected_value: float | None
    expected_low: float | None
    expected_high: float | None
    abs_deviation: float | None
    pct_deviation: float | None
    robust_z: float | None
    severity: str
    data_quality_status: str
    sample_size: float | None


def _severity(z: float, rel: float, days: int, threshold: float = 4.0) -> str:
    az, ar = abs(z), abs(rel)
    level = 0
    if az >= 2 * threshold and ar >= 0.40:
        level = 2
    elif az >= 1.5 * threshold or ar >= 0.40:
        level = 1
    if days >= 3:
        level = min(2, level + 1)
    return ("low", "medium", "high")[level]


def _merge_episodes(days: list[dict]) -> list[list[dict]]:
    days = sorted(days, key=lambda r: r["date"])
    eps: list[list[dict]] = []
    for r in days:
        if eps and (r["date"] - eps[-1][-1]["date"]).days <= 1 and np.sign(r["z"]) == np.sign(eps[-1][-1]["z"]):
            eps[-1].append(r)
        else:
            eps.append([r])
    return eps


def detect(daily: pd.DataFrame, campaigns: pd.DataFrame, last_date: date, lookback_days: int = 90) -> list[Detection]:
    """daily: columns date, campaign_id, spend, impressions, clicks, conversions, revenue."""
    out: list[Detection] = []
    if daily.empty:
        return out
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    for col in ("spend", "impressions", "clicks", "conversions", "revenue"):
        daily[col] = daily[col].astype(float)
    camp = campaigns.set_index("campaign_id")
    start_eval = last_date - timedelta(days=lookback_days - 1)

    for cid, g in daily.groupby("campaign_id"):
        name = str(camp.loc[cid, "campaign_name"]) if cid in camp.index else cid
        platform = str(camp.loc[cid, "platform"]) if cid in camp.index else "unknown"
        status = str(camp.loc[cid, "status"]) if cid in camp.index else "active"
        g = g.set_index("date").sort_index()
        present = set(g.index)
        first = min(present)
        last_row = max(present)
        horizon = last_date if status == "active" else last_row

        # --- missing data -------------------------------------------------
        all_days = [first + timedelta(days=i) for i in range((horizon - first).days + 1)]
        missing = [d for d in all_days if d not in present]
        gaps: list[list[date]] = []
        for d in missing:
            if gaps and (d - gaps[-1][-1]).days == 1:
                gaps[-1].append(d)
            else:
                gaps.append([d])
        for gap in gaps:
            if gap[-1] < start_eval:
                continue
            n = len(gap)
            out.append(Detection(
                "data_completeness", cid, name, platform, gap[0], gap[-1], n, "missing_data",
                0.0, float(n), None, None, -float(n), -100.0, None,
                "high" if n >= 3 else ("medium" if n == 2 else "low"), "missing_data", float(n),
            ))

        # --- tracking gaps -----------------------------------------------------
        tracking_days: set[date] = set()
        tg_rows = []
        dates_sorted = sorted(present)
        for d in dates_sorted:
            if d < start_eval:
                continue
            base = [x for x in dates_sorted if d - timedelta(days=BASELINE_DAYS) <= x < d]
            if len(base) < MIN_BASELINE_POINTS:
                continue
            b = g.loc[base]
            b = b[~((b["conversions"] == 0) & (b["clicks"] > 0))]
            if b.empty:
                continue
            exp_conv = float(b["conversions"].median())
            exp_clicks = float(b["clicks"].median())
            row = g.loc[d]
            if row["conversions"] == 0 and exp_conv >= 8 and row["clicks"] >= 0.5 * exp_clicks:
                tracking_days.add(d)
                tg_rows.append({"date": d, "z": -1.0, "obs": 0.0, "exp": exp_conv, "clicks": float(row["clicks"])})
        for ep in _merge_episodes(tg_rows):
            exp_mean = float(np.mean([r["exp"] for r in ep]))
            out.append(Detection(
                "conversions", cid, name, platform, ep[0]["date"], ep[-1]["date"], len(ep), "tracking_gap",
                0.0, exp_mean, None, None, -exp_mean, -100.0, None,
                "high" if len(ep) >= 2 else "medium", "suspected_tracking_issue",
                float(sum(r["clicks"] for r in ep)),
            ))

        # --- performance metrics -------------------------------------------
        arr = {c: g[c].to_numpy(dtype=float) for c in ("spend", "clicks", "conversions", "revenue")}
        dates_arr = dates_sorted
        idx_of = {d: i for i, d in enumerate(dates_arr)}
        dows = np.array([x.weekday() for x in dates_arr])
        tracked = np.array([x in tracking_days for x in dates_arr])

        def window(i: int, days: int, excl: bool) -> np.ndarray:
            d = dates_arr[i]
            lo = bisect.bisect_left(dates_arr, d - timedelta(days=days))
            ids = np.arange(lo, i)
            if excl and len(ids):
                ids = ids[~tracked[ids]]
            return ids

        for metric in list(ADDITIVE) + list(RATIOS):
            excl = metric in CONVERSION_BASED
            flagged: list[dict] = []
            for d in dates_arr:
                if d < start_eval or (excl and d in tracking_days):
                    continue
                i = idx_of[d]
                base = window(i, BASELINE_DAYS, excl)
                if len(base) < MIN_BASELINE_POINTS:
                    continue
                if metric in ADDITIVE:
                    season = window(i, SEASONAL_DAYS, excl)
                    vals = arr[metric][season]
                    overall = float(vals.mean())
                    if overall <= 0:
                        continue
                    factors = np.ones(7)
                    for k in range(7):
                        sel = vals[dows[season] == k]
                        if len(sel) >= 3:
                            factors[k] = float(sel.mean()) / overall or 1.0
                    f_d = factors[d.weekday()]
                    des = arr[metric][base] / factors[dows[base]]
                    level = float(np.median(des))
                    expected = level * f_d
                    if expected < ADDITIVE[metric]:
                        continue
                    mad = float(np.median(np.abs(des - level))) * 1.4826 * f_d
                    # sampling-noise floor: counts are ~Poisson; money scales with the
                    # underlying click / conversion counts
                    if metric in ("clicks", "conversions"):
                        noise = math.sqrt(expected)
                    elif metric == "spend":
                        exp_clicks = max(float(np.median(arr["clicks"][base])), 1.0)
                        noise = expected * math.sqrt(1.0 / exp_clicks)
                    else:
                        exp_conv = max(float(np.median(arr["conversions"][base])), 1.0)
                        noise = expected * math.sqrt(1.25 / exp_conv)
                    scale = max(mad, noise, 0.03 * expected)
                    obs = float(arr[metric][i])
                    sample = obs
                else:
                    num, den, min_den = RATIOS[metric]
                    if arr[den][i] < min_den:
                        continue
                    den_sum = float(arr[den][base].sum())
                    if den_sum <= 0:
                        continue
                    expected = float(arr[num][base].sum()) / den_sum
                    if expected <= 0:
                        continue
                    ok = base[arr[den][base] >= min_den]
                    if len(ok) < MIN_BASELINE_POINTS // 2:
                        continue
                    daily_ratio = arr[num][ok] / arr[den][ok]
                    mad = float(np.median(np.abs(daily_ratio - np.median(daily_ratio)))) * 1.4826
                    if metric == "conversion_rate":
                        noise = math.sqrt(expected * (1 - expected) / arr[den][i])
                    else:  # CPA / ROAS are driven by a (often small) number of conversions
                        exp_conv = max(float(np.median(arr["conversions"][base])), 1.0)
                        noise = expected * math.sqrt(1.25 / exp_conv)
                    scale = max(mad, noise, 0.03 * expected)
                    obs = float(arr[num][i] / arr[den][i])
                    sample = float(arr[den][i])
                z = (obs - expected) / scale if scale > 0 else 0.0
                rel = (obs - expected) / expected
                if abs(z) >= STORE_Z and abs(rel) >= MIN_REL_DEVIATION:
                    flagged.append({"date": d, "z": z, "obs": obs, "exp": expected, "scale": scale, "rel": rel,
                                    "sample": sample})
            for ep in _merge_episodes(flagged):
                peak = max(ep, key=lambda r: abs(r["z"]))
                obs = float(np.mean([r["obs"] for r in ep]))
                exp_ = float(np.mean([r["exp"] for r in ep]))
                sc = float(np.mean([r["scale"] for r in ep]))
                rel = (obs - exp_) / exp_ if exp_ else 0.0
                low_vol = metric in RATIOS and peak["sample"] < 2 * RATIOS[metric][2]
                out.append(Detection(
                    metric, cid, name, platform, ep[0]["date"], ep[-1]["date"], len(ep),
                    "spike" if peak["z"] > 0 else "drop", obs, exp_, max(0.0, exp_ - 2 * sc), exp_ + 2 * sc,
                    obs - exp_, rel * 100.0, float(peak["z"]), _severity(peak["z"], rel, len(ep)),
                    "low_volume" if low_vol else "ok", float(sum(r["sample"] for r in ep)),
                ))
    return out


def visible(robust_z: float | None, kind: str, sensitivity: str) -> bool:
    if kind in ("missing_data", "tracking_gap") or robust_z is None:
        return True
    return abs(robust_z) >= SENSITIVITY_Z.get(sensitivity, 4.0)
