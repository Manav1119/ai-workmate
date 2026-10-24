import json
from datetime import date

import pandas as pd
import pytest

from app.analytics.anomalies import detect, visible
from seed.generate import GROUND_TRUTH, OUT, generate


def test_generator_is_deterministic_and_labelled_synthetic():
    a, b = generate(), generate()
    assert a == b
    camps, rows = a
    assert len(camps) == 10 and len(rows) == 1065
    days = {r["date"] for r in rows}
    assert min(days) == "2026-06-29" and max(days) == "2026-10-18" and len(days) == 112
    assert len({c["platform"] for c in camps}) == 4
    assert GROUND_TRUTH["synthetic"] is True
    gt = json.loads((OUT / "ground_truth.json").read_text())
    assert gt == json.loads(json.dumps(GROUND_TRUTH))


def test_scenarios_are_present_in_the_data():
    _, rows = generate()
    df = pd.DataFrame(rows)
    for c in ("spend", "revenue"):
        df[c] = df[c].astype(float)
    # S3 missing data: no rows for C007 Sep 14..20
    c7 = set(df[df.campaign_id == "C007"].date)
    assert not any(d in c7 for d in [f"2026-09-{x}" for x in range(14, 21)])
    # S4 tracking gap: zero conversions with normal clicks
    gap = df[(df.campaign_id == "C008") & df.date.between("2026-09-22", "2026-09-25")]
    assert (gap.conversions == 0).all() and (gap.clicks > 500).all()
    # S1 genuine CVR decline for C003
    c3 = df[df.campaign_id == "C003"]
    before = c3[c3.date.between("2026-10-05", "2026-10-11")]
    after = c3[c3.date >= "2026-10-12"]
    ratio = (after.conversions.sum() / after.clicks.sum()) / (before.conversions.sum() / before.clicks.sum())
    assert 0.4 < ratio < 0.65
    # S6 paused campaign has no rows after Aug 31
    assert df[(df.campaign_id == "C010")].date.max() == "2026-08-31"


@pytest.fixture(scope="module")
def detections():
    d = pd.read_csv(OUT / "campaign_daily_metrics.csv")
    c = pd.read_csv(OUT / "campaigns.csv")
    return detect(d, c, date(2026, 10, 18))


def _hits(dets, scen):
    s, e = date.fromisoformat(scen["start"]), date.fromisoformat(scen["end"])
    return [x for x in dets if x.campaign_id == scen["campaign_id"] and x.anomaly_date <= e and x.episode_end >= s]


def test_ground_truth_scenarios_detected_at_balanced_sensitivity(detections):
    vis = [x for x in detections if visible(x.robust_z, x.kind, "balanced")]
    for scen in GROUND_TRUTH["scenarios"]:
        hits = _hits(vis, scen)
        if scen["expect_anomaly"]:
            assert hits, f"{scen['id']} not detected"
            if scen["id"] == "S3_missing_data":
                assert any(h.kind == "missing_data" and h.episode_days == 7 for h in hits)
            if scen["id"] == "S4_tracking_discrepancy":
                assert any(h.kind == "tracking_gap" and h.episode_days == 4 for h in hits)
            if scen["id"] == "S1_conversion_decline":
                assert {"conversion_rate", "cpa"} <= {h.metric for h in hits}


def test_negative_controls(detections):
    vis = [x for x in detections if visible(x.robust_z, x.kind, "balanced")]
    low_vol = [x for x in vis if x.campaign_id == "C006" and x.metric in ("conversion_rate", "cpa", "roas")]
    assert low_vol == []  # minimum sample sizes suppress ratio noise on tiny campaigns
    paused = [x for x in vis if x.campaign_id == "C010" and x.kind == "missing_data"]
    assert paused == []  # a paused campaign's absence is not "missing data"


def test_sensitivity_levels_are_monotonic(detections):
    n = {s: sum(visible(x.robust_z, x.kind, s) for x in detections) for s in ("conservative", "balanced", "sensitive")}
    assert n["conservative"] <= n["balanced"] <= n["sensitive"]
