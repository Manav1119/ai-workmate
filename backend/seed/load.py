"""Load the SYNTHETIC demo dataset and demo account.

    python -m seed.load            (from backend/, after scripts.bootstrap_db)

Idempotent: replaces the public synthetic dataset's rows with the deterministic CSVs,
re-runs anomaly detection, and ensures the demo user exists.
"""

from __future__ import annotations

import csv
import secrets
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import app_tx  # noqa: E402
from app.security.auth import hash_password  # noqa: E402
from app.services.datasets import refresh_stats, run_anomaly_detection  # noqa: E402
from seed.generate import OUT, write  # noqa: E402

DATASET_NAME = "Synthetic marketing demo"
DEMO_EMAIL = "demo@aiworkmate.local"


def load() -> int:
    if not (OUT / "campaign_daily_metrics.csv").exists():
        write()
    with app_tx() as c:
        ds = c.execute(
            text("SELECT id FROM app.datasets WHERE kind = 'synthetic_seed' AND owner_user_id IS NULL ORDER BY id LIMIT 1")
        ).scalar()
        if ds is None:
            ds = c.execute(
                text(
                    "INSERT INTO app.datasets (owner_user_id, name, kind, is_synthetic, reporting_timezone)"
                    " VALUES (NULL, :n, 'synthetic_seed', TRUE, 'UTC') RETURNING id"
                ),
                {"n": DATASET_NAME},
            ).scalar()
        c.execute(text("DELETE FROM analytics.campaign_daily_metrics WHERE dataset_id = :d"), {"d": ds})
        c.execute(text("DELETE FROM analytics.campaigns WHERE dataset_id = :d"), {"d": ds})
        with open(OUT / "campaigns.csv") as f:
            rows = [dict(r, dataset_id=ds) for r in csv.DictReader(f)]
        c.execute(
            text(
                "INSERT INTO analytics.campaigns (dataset_id, campaign_id, campaign_name, platform, objective,"
                " start_date, status) VALUES (:dataset_id, :campaign_id, :campaign_name, :platform, :objective,"
                " CAST(:start_date AS DATE), :status)"
            ),
            rows,
        )
        with open(OUT / "campaign_daily_metrics.csv") as f:
            rows = [dict(r, dataset_id=ds) for r in csv.DictReader(f)]
        c.execute(
            text(
                "INSERT INTO analytics.campaign_daily_metrics (dataset_id, date, campaign_id, spend, impressions,"
                " clicks, conversions, revenue) VALUES (:dataset_id, CAST(:date AS DATE), :campaign_id,"
                " CAST(:spend AS NUMERIC), CAST(:impressions AS BIGINT), CAST(:clicks AS BIGINT),"
                " CAST(:conversions AS BIGINT), CAST(:revenue AS NUMERIC))"
            ),
            rows,
        )
        c.execute(text("UPDATE app.datasets SET loaded_at = now(), name = :n WHERE id = :d"), {"d": ds, "n": DATASET_NAME})
        exists = c.execute(text("SELECT id FROM app.users WHERE email = :e"), {"e": DEMO_EMAIL}).scalar()
        if not exists:
            # Random password: the demo account is reachable only via POST /api/auth/demo
            # (when ALLOW_DEMO_LOGIN=true); nobody needs to know this password.
            c.execute(
                text(
                    "INSERT INTO app.users (email, display_name, password_hash, is_demo, active_dataset_id)"
                    " VALUES (:e, 'Demo Analyst', :h, TRUE, :d)"
                ),
                {"e": DEMO_EMAIL, "h": hash_password(secrets.token_urlsafe(24)), "d": ds},
            )
    stats = refresh_stats(ds)
    n = run_anomaly_detection(ds)
    print(f"loaded SYNTHETIC dataset id={ds}: {stats['n']} rows {stats['first']}..{stats['last']}; {n} anomalies stored")
    return ds


if __name__ == "__main__":
    load()
