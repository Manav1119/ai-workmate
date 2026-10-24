"""Deterministic SYNTHETIC marketing dataset generator.

ALL DATA PRODUCED HERE IS SYNTHETIC. It does not describe any real advertiser.

    python -m seed.generate            (from backend/)  -> writes seed/data/*.csv + ground_truth.json

Design
------
* Fixed seed (``SEED = 20261018``) -> byte-identical output on every run.
* 112 days: Monday 2026-06-29 .. Sunday 2026-10-18 (16 full ISO weeks).
* Grain of campaign_daily_metrics: one row per (date, campaign_id).
* Realistic variation: campaign sizes differ by ~100x, day-of-week profiles per
  channel, slow seasonal drift, multiplicative day noise, binomial click /
  conversion draws and gamma-distributed order values.
* Injected ground-truth scenarios (see GROUND_TRUTH) used by the evaluation suite.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SEED = 20261018
START = date(2026, 6, 29)  # Monday
END = date(2026, 10, 18)  # Sunday
OUT = Path(__file__).resolve().parent / "data"

DOW = {
    # Mon..Sun multipliers
    "ecommerce": [0.92, 0.95, 0.97, 1.00, 1.05, 1.15, 1.12],
    "search": [1.05, 1.05, 1.03, 1.00, 0.97, 0.93, 0.97],
    "b2b": [1.12, 1.15, 1.15, 1.10, 1.00, 0.55, 0.50],
}


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    campaign_name: str
    platform: str
    objective: str
    start_date: date
    status: str
    impressions: float  # daily base
    ctr: float
    cpc: float
    cvr: float  # conversions / clicks
    aov: float  # revenue per conversion
    dow: str
    end_date: date | None = None


CAMPAIGNS: list[Campaign] = [
    Campaign("C001", "Search - Brand", "Google Ads", "Conversions", date(2026, 3, 1), "active", 40_000, 0.080, 0.90, 0.065, 85, "search"),
    Campaign("C002", "Search - Generic", "Google Ads", "Conversions", date(2026, 4, 15), "active", 90_000, 0.035, 1.60, 0.035, 92, "search"),
    Campaign("C003", "Prospecting - Lookalike", "Meta", "Conversions", date(2026, 5, 10), "active", 250_000, 0.012, 0.85, 0.040, 78, "ecommerce"),
    Campaign("C004", "Retargeting - Cart Abandoners", "Meta", "Conversions", date(2026, 5, 10), "active", 60_000, 0.020, 1.10, 0.070, 95, "ecommerce"),
    Campaign("C005", "Spark Ads - UGC", "TikTok", "Conversions", date(2026, 6, 1), "active", 300_000, 0.009, 0.45, 0.022, 60, "ecommerce"),
    Campaign("C006", "Lead Gen - Decision Makers", "LinkedIn", "Leads", date(2026, 6, 15), "active", 8_000, 0.006, 7.50, 0.030, 220, "b2b"),
    Campaign("C007", "Display - Remarketing", "Google Ads", "Conversions", date(2026, 4, 1), "active", 120_000, 0.004, 0.70, 0.030, 70, "ecommerce"),
    Campaign("C008", "Shopping - Catalog", "Google Ads", "Sales", date(2026, 5, 1), "active", 70_000, 0.018, 0.75, 0.050, 68, "ecommerce"),
    Campaign("C009", "Video - Awareness", "Meta", "Awareness", date(2026, 6, 1), "active", 400_000, 0.003, 0.30, 0.004, 70, "ecommerce"),
    Campaign("C010", "Interest Prospecting - Q3 Test", "TikTok", "Conversions", date(2026, 6, 1), "paused", 150_000, 0.008, 0.50, 0.020, 60, "ecommerce", end_date=date(2026, 8, 31)),
]

# --- Ground-truth scenarios ------------------------------------------------
C003_DROP_START = date(2026, 10, 12)
C003_CVR_FACTOR = 0.52
C005_SCALE_START = date(2026, 9, 28)
C005_BUDGET_FACTOR = 1.70
C005_CVR_FACTOR = 0.62
C007_GAP = (date(2026, 9, 14), date(2026, 9, 20))
C008_TRACKING = (date(2026, 9, 22), date(2026, 9, 25))

GROUND_TRUTH = {
    "dataset": "synthetic_demo_v1",
    "synthetic": True,
    "seed": SEED,
    "date_range": [START.isoformat(), END.isoformat()],
    "anchor_date": END.isoformat(),
    "scenarios": [
        {
            "id": "S1_conversion_decline",
            "campaign_id": "C003",
            "type": "performance_change",
            "description": "Genuine conversion-rate decline on Meta 'Prospecting - Lookalike': CVR multiplied by 0.52 from 2026-10-12 while clicks are unchanged.",
            "start": C003_DROP_START.isoformat(),
            "end": END.isoformat(),
            "expected_detection_metrics": ["conversion_rate", "conversions", "cpa", "revenue", "roas"],
            "expect_anomaly": True,
        },
        {
            "id": "S2_spend_without_revenue",
            "campaign_id": "C005",
            "type": "performance_change",
            "description": "TikTok 'Spark Ads - UGC' budget scaled 1.7x from 2026-09-28 while CVR fell to 0.62x, so revenue grows ~5% and ROAS falls ~38%.",
            "start": C005_SCALE_START.isoformat(),
            "end": END.isoformat(),
            "expected_detection_metrics": ["spend", "clicks", "roas", "conversion_rate", "cpa"],
            "expect_anomaly": True,
        },
        {
            "id": "S3_missing_data",
            "campaign_id": "C007",
            "type": "data_quality",
            "description": "No rows delivered for 'Display - Remarketing' 2026-09-14..2026-09-20 (simulated pipeline outage). The campaign was running.",
            "start": C007_GAP[0].isoformat(),
            "end": C007_GAP[1].isoformat(),
            "expected_detection_metrics": ["missing_data"],
            "expect_anomaly": True,
        },
        {
            "id": "S4_tracking_discrepancy",
            "campaign_id": "C008",
            "type": "data_quality",
            "description": "'Shopping - Catalog' reports 0 conversions and 0 revenue 2026-09-22..2026-09-25 while spend and clicks are normal (broken conversion tag).",
            "start": C008_TRACKING[0].isoformat(),
            "end": C008_TRACKING[1].isoformat(),
            "expected_detection_metrics": ["tracking_gap", "conversions", "revenue"],
            "expect_anomaly": True,
        },
        {
            "id": "S5_low_volume_noise",
            "campaign_id": "C006",
            "type": "negative_control",
            "description": "LinkedIn lead gen campaign with ~50 clicks/day and ~1.4 conversions/day. Ratio swings are noise; ratio-metric anomalies should be suppressed by minimum sample sizes.",
            "start": START.isoformat(),
            "end": END.isoformat(),
            "expected_detection_metrics": [],
            "expect_anomaly": False,
        },
        {
            "id": "S6_paused_campaign",
            "campaign_id": "C010",
            "type": "negative_control",
            "description": "TikTok test campaign paused after 2026-08-31. Absence of rows afterwards is expected and must not be flagged as missing data.",
            "start": "2026-09-01",
            "end": END.isoformat(),
            "expected_detection_metrics": [],
            "expect_anomaly": False,
        },
    ],
}


def _seasonal(t: int) -> float:
    return 1.0 + 0.05 * math.cos(2 * math.pi * t / 112.0)


def generate(seed: int = SEED) -> tuple[list[dict], list[dict]]:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    n_days = (END - START).days + 1
    for c in CAMPAIGNS:
        for t in range(n_days):
            d = START + timedelta(days=t)
            # draw random numbers for every day (even skipped ones) so that
            # scenario edits never shift the random stream of other rows
            z_impr, z_cvr, z_cpc = rng.normal(0, 1, 3)
            u_click, u_conv, u_rev = rng.random(3)
            if d < c.start_date or (c.end_date and d > c.end_date):
                continue
            if c.campaign_id == "C007" and C007_GAP[0] <= d <= C007_GAP[1]:
                continue  # missing data scenario

            budget = 1.0
            cvr = c.cvr
            cpc = c.cpc
            if c.campaign_id == "C005" and d >= C005_SCALE_START:
                budget = C005_BUDGET_FACTOR
                cvr *= C005_CVR_FACTOR
                cpc *= 1.04
            if c.campaign_id == "C003" and d >= C003_DROP_START:
                cvr *= C003_CVR_FACTOR

            dow = DOW[c.dow][d.weekday()]
            impressions = int(round(c.impressions * budget * dow * _seasonal(t) * math.exp(0.06 * z_impr)))
            # binomial draws via a per-row generator derived from the uniforms -> deterministic
            sub = np.random.default_rng([seed, t, int(c.campaign_id[1:]), int(u_click * 1e9)])
            clicks = int(sub.binomial(impressions, c.ctr))
            day_cvr = min(0.95, cvr * dow ** 0.5 * math.exp(0.05 * z_cvr))
            conversions = int(sub.binomial(clicks, day_cvr))
            spend = round(clicks * cpc * math.exp(0.04 * z_cpc), 2)
            if conversions > 0:
                k = 4.0
                revenue = round(float(sub.gamma(conversions * k, c.aov / k)), 2)
            else:
                revenue = 0.0
            if c.campaign_id == "C008" and C008_TRACKING[0] <= d <= C008_TRACKING[1]:
                conversions, revenue = 0, 0.0  # tracking discrepancy scenario
            rows.append(
                {
                    "date": d.isoformat(),
                    "campaign_id": c.campaign_id,
                    "spend": f"{spend:.2f}",
                    "impressions": impressions,
                    "clicks": clicks,
                    "conversions": conversions,
                    "revenue": f"{revenue:.2f}",
                }
            )
    campaigns = [
        {
            "campaign_id": c.campaign_id,
            "campaign_name": c.campaign_name,
            "platform": c.platform,
            "objective": c.objective,
            "start_date": c.start_date.isoformat(),
            "status": c.status,
        }
        for c in CAMPAIGNS
    ]
    return campaigns, rows


def write(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    campaigns, rows = generate()
    with open(out / "campaigns.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(campaigns[0]))
        w.writeheader()
        w.writerows(campaigns)
    with open(out / "campaign_daily_metrics.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (out / "ground_truth.json").write_text(json.dumps(GROUND_TRUTH, indent=2) + "\n")
    print(f"SYNTHETIC data written: {len(campaigns)} campaigns, {len(rows)} campaign-day rows -> {out}")


if __name__ == "__main__":
    write()
