import random

import pytest

from app.analytics.contribution import contributions, log_mean


def _seg(spend, clicks, conv, rev, impr=10000):
    return {"spend": spend, "clicks": clicks, "conversions": conv, "revenue": rev, "impressions": impr}


def test_additive_contributions_sum_to_total():
    cur = {"A": _seg(100, 50, 5, 500), "B": _seg(200, 80, 8, 900)}
    prev = {"A": _seg(120, 60, 10, 700), "B": _seg(180, 70, 7, 800)}
    r = contributions("conversions", cur, prev)
    assert r.total_change == -4
    assert sum(s.contribution for s in r.segments) == pytest.approx(r.total_change)
    assert r.segments[0].segment == "A"  # largest negative first when total fell


@pytest.mark.parametrize("metric", ["cpa", "roas", "conversion_rate", "ctr", "cpc", "aov"])
def test_ratio_decomposition_is_exact_on_random_data(metric):
    rng = random.Random(7)
    for _ in range(50):
        segs = [chr(65 + i) for i in range(rng.randint(2, 7))]
        cur = {s: _seg(rng.uniform(10, 5000), rng.randint(20, 3000), rng.randint(1, 200), rng.uniform(10, 20000),
                       rng.randint(5000, 90000)) for s in segs}
        prev = {s: _seg(rng.uniform(10, 5000), rng.randint(20, 3000), rng.randint(1, 200), rng.uniform(10, 20000),
                        rng.randint(5000, 90000)) for s in segs}
        r = contributions(metric, cur, prev)
        assert "LMDI" in r.method
        assert r.check_sum == pytest.approx(r.total_change, rel=1e-9, abs=1e-9)
        for s in r.segments:
            assert s.numerator_effect + s.denominator_effect == pytest.approx(s.contribution)


def test_cpa_attributes_conversion_collapse_to_the_right_segment():
    # Segment X keeps spend flat but loses half its conversions -> it must be the top CPA contributor,
    # even though its spend (CPA numerator) did not change.
    prev = {"X": _seg(1000, 1000, 50, 4000), "Y": _seg(1000, 1000, 50, 4000)}
    cur = {"X": _seg(1000, 1000, 25, 2000), "Y": _seg(1050, 1000, 52, 4100)}
    r = contributions("cpa", cur, prev)
    assert r.total_change > 0
    assert r.segments[0].segment == "X"
    assert abs(r.segments[0].denominator_effect) > abs(r.segments[0].numerator_effect)


def test_zero_denominator_period_skips_with_note():
    cur = {"A": _seg(100, 0, 0, 0)}
    prev = {"A": _seg(100, 10, 1, 10)}
    r = contributions("conversion_rate", cur, prev)
    assert r.segments == [] and "undefined" in r.notes[0]


def test_zero_numerator_falls_back_to_share_method():
    cur = {"A": _seg(100, 100, 0, 0), "B": _seg(100, 100, 0, 0)}
    prev = {"A": _seg(100, 100, 5, 50), "B": _seg(100, 100, 3, 30)}
    r = contributions("conversion_rate", cur, prev)
    assert "share" in r.method
    assert r.check_sum == pytest.approx(r.total_change)


def test_low_sample_and_offsetting_notes():
    cur = {"big": _seg(1000, 5000, 100, 9000), "tiny": _seg(10, 20, 2, 50)}
    prev = {"big": _seg(1000, 5000, 150, 9000), "tiny": _seg(10, 20, 0, 0)}
    r = contributions("conversion_rate", cur, prev)
    assert any("Low sample" in n for n in r.notes)


def test_log_mean():
    assert log_mean(2, 2) == 2
    assert log_mean(1, 4) == pytest.approx(3 / 1.3862943611198906)
    with pytest.raises(ValueError):
        log_mean(0, 1)
