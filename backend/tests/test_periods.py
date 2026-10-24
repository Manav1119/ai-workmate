from datetime import date, datetime, timezone

import pytest

from app.analytics.periods import (
    PeriodError, anchor_date, comparison_for, coverage_issue, resolve, to_reporting_date, today_in,
)


@pytest.mark.parametrize(
    "anchor,start,end",
    [
        (date(2026, 10, 18), date(2026, 10, 12), date(2026, 10, 18)),  # Sunday anchor: that week is complete
        (date(2026, 10, 17), date(2026, 10, 5), date(2026, 10, 11)),  # Saturday: previous complete week
        (date(2026, 10, 19), date(2026, 10, 12), date(2026, 10, 18)),  # Monday
        (date(2026, 10, 14), date(2026, 10, 5), date(2026, 10, 11)),  # Wednesday
    ],
)
def test_last_week_is_last_complete_monday_to_sunday(anchor, start, end):
    p = resolve("last_week", anchor)
    assert (p.start, p.end) == (start, end)
    assert p.start.weekday() == 0 and p.end.weekday() == 6 and p.days == 7


def test_previous_period_has_equal_length_including_partial_weeks():
    cur = resolve("this_week", date(2026, 10, 14))  # Mon..Wed
    assert (cur.start, cur.end, cur.days) == (date(2026, 10, 12), date(2026, 10, 14), 3)
    prev = comparison_for(cur, "previous_period")
    assert (prev.start, prev.end, prev.days) == (date(2026, 10, 9), date(2026, 10, 11), 3)
    p30 = resolve("last_30_days", date(2026, 10, 18))
    c30 = comparison_for(p30, "previous_period")
    assert c30.days == 30 and c30.end == date(2026, 9, 18)


def test_calendar_month_compares_with_previous_calendar_month():
    lm = resolve("last_month", date(2026, 10, 18))
    assert (lm.start, lm.end) == (date(2026, 9, 1), date(2026, 9, 30))
    prev = comparison_for(lm, "previous_period")
    assert (prev.start, prev.end) == (date(2026, 8, 1), date(2026, 8, 31))
    # anchor on the last day of a month: that month is complete
    assert resolve("last_month", date(2026, 9, 30)).start == date(2026, 9, 1)


def test_same_period_last_year_and_errors():
    p = resolve("custom", date(2026, 10, 18), start=date(2026, 10, 1), end=date(2026, 10, 7))
    ly = comparison_for(p, "same_period_last_year")
    assert (ly.start, ly.end) == (date(2025, 10, 1), date(2025, 10, 7))
    with pytest.raises(PeriodError):
        resolve("custom", date(2026, 10, 18), start=date(2026, 10, 7), end=date(2026, 10, 1))
    with pytest.raises(PeriodError):
        resolve("next_century", date(2026, 10, 18))
    assert comparison_for(p, "none") is None


def test_timezone_boundaries():
    # 20:00 UTC on Oct 11 is already Oct 12 in India (UTC+5:30) but still Oct 11 in New York
    ts = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    assert to_reporting_date(ts, "Asia/Kolkata") == date(2026, 10, 12)
    assert to_reporting_date(ts, "America/New_York") == date(2026, 10, 11)
    assert to_reporting_date(datetime(2026, 10, 11, 23, 59), "UTC") == date(2026, 10, 11)  # naive -> UTC
    now = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
    assert today_in("Asia/Kolkata", now) == date(2026, 10, 19)
    assert today_in("UTC", now) == date(2026, 10, 18)
    # anchor never runs ahead of "today" in the reporting timezone
    assert anchor_date(date(2026, 10, 19), "UTC", now) == date(2026, 10, 18)
    assert anchor_date(date(2026, 10, 19), "Asia/Kolkata", now) == date(2026, 10, 19)


def test_coverage_issue():
    p = resolve("last_7_days", date(2026, 10, 18))
    assert coverage_issue(p, date(2026, 6, 29), date(2026, 10, 18)) is None
    assert "partly" in coverage_issue(p, date(2026, 10, 15), date(2026, 10, 18))
    assert "entirely outside" in coverage_issue(p, date(2025, 1, 1), date(2025, 2, 1))
