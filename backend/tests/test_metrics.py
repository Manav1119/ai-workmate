import math

import pytest

from app.analytics.metrics import (
    METRICS, change, compute_all, compute_metric, format_value, pct_change, required_measures, resolve_metric, sample_ok,
)


def test_ratio_of_sums_not_average_of_daily_ratios():
    days = [
        {"spend": 100, "conversions": 1, "clicks": 10, "revenue": 50, "impressions": 1000},
        {"spend": 100, "conversions": 9, "clicks": 90, "revenue": 950, "impressions": 9000},
    ]
    totals = {k: sum(d[k] for d in days) for k in days[0]}
    avg_daily_cpa = sum(d["spend"] / d["conversions"] for d in days) / 2  # 55.56 (wrong)
    assert compute_metric("cpa", totals) == pytest.approx(20.0)  # 200 / 10
    assert compute_metric("cpa", totals) != pytest.approx(avg_daily_cpa)
    assert compute_metric("roas", totals) == pytest.approx(5.0)
    assert compute_metric("conversion_rate", totals) == pytest.approx(0.1)  # denominator: clicks
    assert compute_metric("ctr", totals) == pytest.approx(0.01)


@pytest.mark.parametrize("metric,den", [("cpa", "conversions"), ("roas", "spend"), ("conversion_rate", "clicks"),
                                        ("ctr", "impressions"), ("cpc", "clicks"), ("aov", "conversions")])
def test_zero_denominator_is_undefined_not_zero_or_inf(metric, den):
    totals = {"spend": 10, "impressions": 100, "clicks": 5, "conversions": 2, "revenue": 30, den: 0}
    assert compute_metric(metric, totals) is None


def test_missing_values_are_undefined():
    assert compute_metric("cpa", {"spend": None, "conversions": 3}) is None
    assert compute_metric("spend", {"spend": float("nan")}) is None


@pytest.mark.parametrize(
    "cur,cmp_,expected,note",
    [
        (110, 100, 10.0, None),
        (90, 100, -10.0, None),
        (5, -10, 150.0, None),  # absolute comparison value in the denominator
        (0, 0, 0.0, None),
        (5, 0, None, "zero"),
        (None, 10, None, "no current"),
        (10, None, None, "missing baseline"),
        (None, None, None, "both"),
    ],
)
def test_pct_change_edge_cases(cur, cmp_, expected, note):
    v, why = pct_change(cur, cmp_)
    if expected is None:
        assert v is None and note in why
    else:
        assert v == pytest.approx(expected) and why is None


def test_change_object():
    ch = change(80.0, 100.0)
    assert ch.abs_change == -20 and ch.pct_change == pytest.approx(-20)
    ch = change(None, 3.0)
    assert ch.abs_change is None and ch.pct_change is None and ch.note


def test_every_metric_is_documented():
    for m in METRICS.values():
        assert m.definition and m.formula and m.source_columns and m.zero_handling and m.missing_handling
        if m.aggregation == "ratio_of_sums":
            assert m.numerator and m.denominator


def test_required_measures_and_resolution():
    assert required_measures(["cpa", "roas"]) == ["spend", "conversions", "revenue"]
    assert resolve_metric("CVR") == "conversion_rate"
    assert resolve_metric("cost per acquisition") == "cpa"
    assert resolve_metric("nonsense") is None


def test_sample_size_gate_and_formatting():
    ok, why = sample_ok("conversion_rate", {"clicks": 50})
    assert not ok and "minimum" in why
    assert sample_ok("conversion_rate", {"clicks": 5000})[0]
    assert format_value("spend", 1234.5) == "$1,234.50"
    assert format_value("conversion_rate", 0.0374) == "3.74%"
    assert format_value("roas", 3.333) == "3.33x"
    assert format_value("cpa", None) == "n/a"
    assert all(v is None or not math.isinf(v) for v in compute_all({"spend": 1, "clicks": 0}).values())
