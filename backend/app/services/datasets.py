"""Dataset helpers: stats, freshness, anomaly detection refresh, raw frames for engines."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text

from app.analytics import anomalies as anomaly_engine
from app.analytics.periods import today_in
from app.config import get_settings
from app.db import app_tx


def load_frames(dataset_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    with app_tx() as c:
        daily = pd.DataFrame(
            c.execute(
                text(
                    "SELECT date, campaign_id, spend::float AS spend, impressions, clicks, conversions,"
                    " revenue::float AS revenue FROM analytics.campaign_daily_metrics WHERE dataset_id = :d"
                    " ORDER BY date, campaign_id"
                ),
                {"d": dataset_id},
            ).mappings().all()
        )
        camps = pd.DataFrame(
            c.execute(
                text(
                    "SELECT campaign_id, campaign_name, platform, objective, start_date, status"
                    " FROM analytics.campaigns WHERE dataset_id = :d ORDER BY campaign_id"
                ),
                {"d": dataset_id},
            ).mappings().all()
        )
    if daily.empty:
        daily = pd.DataFrame(columns=["date", "campaign_id", "spend", "impressions", "clicks", "conversions", "revenue"])
    if camps.empty:
        camps = pd.DataFrame(columns=["campaign_id", "campaign_name", "platform", "objective", "start_date", "status"])
    return daily, camps


def refresh_stats(dataset_id: int) -> dict:
    with app_tx() as c:
        r = c.execute(
            text(
                "SELECT COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last FROM analytics.campaign_daily_metrics"
                " WHERE dataset_id = :d"
            ),
            {"d": dataset_id},
        ).mappings().one()
        c.execute(
            text("UPDATE app.datasets SET row_count = :n, first_date = :f, last_date = :l WHERE id = :d"),
            {"n": r["n"], "f": r["first"], "l": r["last"], "d": dataset_id},
        )
    return dict(r)


def run_anomaly_detection(dataset_id: int) -> int:
    """Recompute anomalies, preserving rows (and user triage states) that are re-detected."""
    s = get_settings()
    daily, camps = load_frames(dataset_id)
    with app_tx() as c:
        last = c.execute(text("SELECT last_date FROM app.datasets WHERE id = :d"), {"d": dataset_id}).scalar()
    if last is None or daily.empty:
        return 0
    dets = anomaly_engine.detect(daily, camps, last, lookback_days=max(s.anomaly_lookback_days, 90))
    keys = []
    with app_tx() as c:
        for d in dets:
            row = c.execute(
                text(
                    """
                    INSERT INTO app.anomalies (dataset_id, metric, campaign_id, campaign_name, platform, anomaly_date,
                        episode_end, episode_days, kind, observed_value, expected_value, expected_low, expected_high,
                        abs_deviation, pct_deviation, robust_z, severity, data_quality_status, sample_size,
                        detector_version)
                    VALUES (:ds, :metric, :campaign_id, :campaign_name, :platform, :anomaly_date, :episode_end,
                        :episode_days, :kind, :observed_value, :expected_value, :expected_low, :expected_high,
                        :abs_deviation, :pct_deviation, :robust_z, :severity, :data_quality_status, :sample_size, :ver)
                    ON CONFLICT (dataset_id, metric, campaign_id, anomaly_date, kind) DO UPDATE SET
                        episode_end = EXCLUDED.episode_end, episode_days = EXCLUDED.episode_days,
                        observed_value = EXCLUDED.observed_value, expected_value = EXCLUDED.expected_value,
                        expected_low = EXCLUDED.expected_low, expected_high = EXCLUDED.expected_high,
                        abs_deviation = EXCLUDED.abs_deviation, pct_deviation = EXCLUDED.pct_deviation,
                        robust_z = EXCLUDED.robust_z, severity = EXCLUDED.severity,
                        data_quality_status = EXCLUDED.data_quality_status, sample_size = EXCLUDED.sample_size,
                        detector_version = EXCLUDED.detector_version
                    RETURNING id
                    """
                ),
                {**d.__dict__, "ds": dataset_id, "ver": anomaly_engine.DETECTOR_VERSION},
            ).scalar()
            keys.append(row)
        if keys:
            c.execute(
                text("DELETE FROM app.anomalies WHERE dataset_id = :d AND NOT (id = ANY(:ids))"),
                {"d": dataset_id, "ids": keys},
            )
        else:
            c.execute(text("DELETE FROM app.anomalies WHERE dataset_id = :d"), {"d": dataset_id})
    return len(dets)


def freshness(ds: dict, tz: str, now: datetime | None = None) -> dict:
    last: date | None = ds.get("last_date")
    today = today_in(tz, now)
    days_stale = (today - last).days if last else None
    status = "unknown"
    if days_stale is not None:
        status = "fresh" if days_stale <= 1 else ("stale" if days_stale <= 7 else "very_stale")
    with app_tx() as c:
        missing = c.execute(
            text(
                "SELECT COUNT(*) FROM app.anomalies WHERE dataset_id = :d AND kind = 'missing_data'"
                " AND episode_end >= :since"
            ),
            {"d": ds["id"], "since": (last or today) - timedelta(days=30)},
        ).scalar()
    return {
        "last_data_date": last.isoformat() if last else None,
        "first_data_date": ds["first_date"].isoformat() if ds.get("first_date") else None,
        "today": today.isoformat(),
        "reporting_timezone": tz,
        "days_since_last_data": days_stale,
        "status": status,
        "missing_data_episodes_last_30d": int(missing or 0),
        "loaded_at": ds["loaded_at"].isoformat() if ds.get("loaded_at") else None,
        "is_synthetic": bool(ds.get("is_synthetic")),
    }
