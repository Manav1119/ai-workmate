-- 001: schemas, analytics tables, row-level security
-- Executed by the admin role via scripts/bootstrap_db.py. Role names are fixed;
-- role passwords are set by the bootstrap script from environment variables.

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS analytics;

-- Datasets own analytics rows. dataset 1 = seeded synthetic demo data (public).
CREATE TABLE IF NOT EXISTS app.users (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    is_demo         BOOLEAN NOT NULL DEFAULT FALSE,
    reporting_timezone TEXT NOT NULL DEFAULT 'UTC',
    anomaly_sensitivity TEXT NOT NULL DEFAULT 'balanced'
        CHECK (anomaly_sensitivity IN ('conservative', 'balanced', 'sensitive')),
    active_dataset_id INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.datasets (
    id              SERIAL PRIMARY KEY,
    owner_user_id   INTEGER REFERENCES app.users(id) ON DELETE CASCADE,  -- NULL = public demo
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('synthetic_seed', 'csv_upload')),
    is_synthetic    BOOLEAN NOT NULL DEFAULT FALSE,
    reporting_timezone TEXT NOT NULL DEFAULT 'UTC',
    row_count       INTEGER NOT NULL DEFAULT 0,
    first_date      DATE,
    last_date       DATE,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    import_summary  JSONB
);

-- Grain: one row per campaign per dataset.
CREATE TABLE IF NOT EXISTS analytics.campaigns (
    dataset_id      INTEGER NOT NULL REFERENCES app.datasets(id) ON DELETE CASCADE,
    campaign_id     TEXT NOT NULL,
    campaign_name   TEXT NOT NULL,
    platform        TEXT NOT NULL,
    objective       TEXT NOT NULL,
    start_date      DATE,
    status          TEXT NOT NULL,
    PRIMARY KEY (dataset_id, campaign_id)
);

-- Grain: one row per campaign per reporting-timezone calendar date.
-- The primary key prevents double-counting the same campaign-day.
CREATE TABLE IF NOT EXISTS analytics.campaign_daily_metrics (
    dataset_id      INTEGER NOT NULL,
    date            DATE NOT NULL,
    campaign_id     TEXT NOT NULL,
    spend           NUMERIC(14, 2) NOT NULL CHECK (spend >= 0),
    impressions     BIGINT NOT NULL CHECK (impressions >= 0),
    clicks          BIGINT NOT NULL CHECK (clicks >= 0),
    conversions     BIGINT NOT NULL CHECK (conversions >= 0),
    revenue         NUMERIC(14, 2) NOT NULL CHECK (revenue >= 0),
    PRIMARY KEY (dataset_id, date, campaign_id),
    FOREIGN KEY (dataset_id, campaign_id) REFERENCES analytics.campaigns(dataset_id, campaign_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS cdm_dataset_date ON analytics.campaign_daily_metrics (dataset_id, date);

-- Row-level security: the read-only role only ever sees rows of the dataset
-- selected by the executor for the current transaction (SET LOCAL app.dataset_id).
-- The SQL validator additionally blocks set_config()/SET so generated SQL cannot change it.
ALTER TABLE analytics.campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics.campaign_daily_metrics ENABLE ROW LEVEL SECURITY;
