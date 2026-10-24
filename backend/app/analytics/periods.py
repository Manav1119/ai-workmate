"""Time-range resolution and comparison-period logic.

Relative ranges ("last week", "last 30 days") are resolved deterministically in code
against the dataset's *anchor date* (the latest date with data, capped at "today" in
the reporting timezone). The LLM never computes calendar dates.

Conventions (documented in docs/METRIC_DICTIONARY.md):
* Weeks are ISO weeks, Monday..Sunday.
* ``last_week`` is the most recent *complete* Monday..Sunday week ending on or before the anchor.
* ``this_week`` is the week containing the anchor, up to the anchor (may be partial).
* ``previous_period`` comparison = the same number of days immediately before the current
  range, so partial periods are always compared with an equal-length period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Preset = Literal[
    "last_7_days", "last_14_days", "last_28_days", "last_30_days", "last_90_days",
    "last_week", "this_week", "last_month", "this_month", "all_time", "custom",
]
ComparisonKind = Literal["previous_period", "same_period_last_year", "none"]

PRESETS: tuple[str, ...] = (
    "last_7_days", "last_14_days", "last_28_days", "last_30_days", "last_90_days",
    "last_week", "this_week", "last_month", "this_month", "all_time", "custom",
)


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label, "days": self.days}


class PeriodError(ValueError):
    pass


def today_in(tz: str, now: datetime | None = None) -> date:
    now = now or datetime.now(tz=ZoneInfo("UTC"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    return now.astimezone(ZoneInfo(tz)).date()


def to_reporting_date(ts: datetime, tz: str) -> date:
    """Convert an event timestamp into the reporting-timezone calendar date.

    Naive timestamps are interpreted as UTC.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(ZoneInfo(tz)).date()


def anchor_date(last_data_date: date, tz: str, now: datetime | None = None) -> date:
    return min(last_data_date, today_in(tz, now))


def _fmt(d: date) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def resolve(
    preset: str,
    anchor: date,
    first_data_date: date | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Period:
    if preset == "custom":
        if not start or not end:
            raise PeriodError("custom range requires start and end dates")
        if start > end:
            raise PeriodError("start date is after end date")
        return Period(start, end, f"{_fmt(start)} – {_fmt(end)}")
    if preset.startswith("last_") and preset.endswith("_days"):
        n = int(preset.split("_")[1])
        s = anchor - timedelta(days=n - 1)
        return Period(s, anchor, f"Last {n} days ({_fmt(s)} – {_fmt(anchor)})")
    if preset == "last_week":
        # most recent complete Mon..Sun week ending on/before anchor
        end_ = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        s = end_ - timedelta(days=6)
        return Period(s, end_, f"Week of {_fmt(s)} – {_fmt(end_)}")
    if preset == "this_week":
        s = anchor - timedelta(days=anchor.weekday())
        return Period(s, anchor, f"This week to date ({_fmt(s)} – {_fmt(anchor)})")
    if preset == "this_month":
        s = anchor.replace(day=1)
        return Period(s, anchor, f"Month to date ({_fmt(s)} – {_fmt(anchor)})")
    if preset == "last_month":
        first_this = anchor.replace(day=1)
        e = first_this - timedelta(days=1)
        # if anchor is the last day of its month, the anchor month is complete -> use it
        if (anchor + timedelta(days=1)).month != anchor.month:
            e = anchor
        s = e.replace(day=1)
        return Period(s, e, f"{s.strftime('%B %Y')}")
    if preset == "all_time":
        s = first_data_date or anchor - timedelta(days=89)
        return Period(s, anchor, f"All data ({_fmt(s)} – {_fmt(anchor)})")
    raise PeriodError(f"unsupported time range preset: {preset}")


def comparison_for(current: Period, kind: str) -> Period | None:
    if kind == "none":
        return None
    if kind == "previous_period":
        # calendar months compare with the previous calendar month
        if current.start.day == 1 and (current.end + timedelta(days=1)).day == 1:
            e = current.start - timedelta(days=1)
            s = e.replace(day=1)
            return Period(s, e, s.strftime("%B %Y"))
        e = current.start - timedelta(days=1)
        s = e - timedelta(days=current.days - 1)
        return Period(s, e, f"Previous {current.days} days ({_fmt(s)} – {_fmt(e)})")
    if kind == "same_period_last_year":
        try:
            s = current.start.replace(year=current.start.year - 1)
            e = current.end.replace(year=current.end.year - 1)
        except ValueError:  # Feb 29
            s = current.start - timedelta(days=365)
            e = current.end - timedelta(days=365)
        return Period(s, e, f"Same period last year ({_fmt(s)} – {_fmt(e)})")
    raise PeriodError(f"unsupported comparison: {kind}")


def coverage_issue(period: Period, first_data: date | None, last_data: date | None) -> str | None:
    if first_data is None or last_data is None:
        return "dataset has no data"
    if period.end < first_data or period.start > last_data:
        return f"{period.label} is entirely outside the available data ({_fmt(first_data)} – {_fmt(last_data)})"
    if period.start < first_data or period.end > last_data:
        return f"{period.label} is only partly covered by available data ({_fmt(first_data)} – {_fmt(last_data)})"
    return None
