-- 002: application state (investigations, anomalies, reports, audit)

CREATE TABLE IF NOT EXISTS app.analyses (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    dataset_id      INTEGER NOT NULL REFERENCES app.datasets(id) ON DELETE CASCADE,
    parent_id       INTEGER REFERENCES app.analyses(id) ON DELETE SET NULL,
    question        TEXT NOT NULL,
    title           TEXT,
    status          TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'needs_clarification', 'unsupported', 'rejected')),
    mode            TEXT NOT NULL CHECK (mode IN ('llm', 'demo')),
    intent          TEXT,
    plan            JSONB,
    generated_sql   TEXT,
    sql_validation  JSONB,
    result          JSONB,   -- aggregated rows (capped) + deterministic calculations
    explanation     JSONB,
    pipeline_trace  JSONB,
    error_code      TEXT,
    error_message   TEXT,
    saved           BOOLEAN NOT NULL DEFAULT FALSE,
    data_as_of      DATE,
    llm_usage       JSONB,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analyses_user_created ON app.analyses (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS app.anomalies (
    id              SERIAL PRIMARY KEY,
    dataset_id      INTEGER NOT NULL REFERENCES app.datasets(id) ON DELETE CASCADE,
    metric          TEXT NOT NULL,
    campaign_id     TEXT NOT NULL,
    campaign_name   TEXT NOT NULL,
    platform        TEXT NOT NULL,
    anomaly_date    DATE NOT NULL,          -- first day of the anomalous episode
    episode_end     DATE NOT NULL,
    episode_days    INTEGER NOT NULL DEFAULT 1,
    kind            TEXT NOT NULL CHECK (kind IN ('drop', 'spike', 'missing_data', 'tracking_gap')),
    observed_value  DOUBLE PRECISION,
    expected_value  DOUBLE PRECISION,
    expected_low    DOUBLE PRECISION,
    expected_high   DOUBLE PRECISION,
    abs_deviation   DOUBLE PRECISION,
    pct_deviation   DOUBLE PRECISION,
    robust_z        DOUBLE PRECISION,
    severity        TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    data_quality_status TEXT NOT NULL CHECK (data_quality_status IN ('ok', 'missing_data', 'suspected_tracking_issue', 'low_volume')),
    sample_size     DOUBLE PRECISION,
    detector_version TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, metric, campaign_id, anomaly_date, kind)
);

-- Per-user workflow state so shared demo datasets don't leak triage decisions across users.
CREATE TABLE IF NOT EXISTS app.anomaly_states (
    anomaly_id      INTEGER NOT NULL REFERENCES app.anomalies(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('new', 'investigating', 'resolved', 'not_actionable')),
    note            TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (anomaly_id, user_id)
);

CREATE TABLE IF NOT EXISTS app.reports (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    analysis_id     INTEGER REFERENCES app.analyses(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('investigation', 'briefing')),
    title           TEXT NOT NULL,
    markdown        TEXT NOT NULL,
    data_as_of      DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.query_audit (
    id              BIGSERIAL PRIMARY KEY,
    request_id      TEXT,
    user_id         INTEGER,
    analysis_id     INTEGER,
    dataset_id      INTEGER,
    source          TEXT NOT NULL,          -- llm | demo_builder | crosscheck | coverage | anomaly_engine
    sql_text        TEXT NOT NULL,
    sql_sha256      TEXT NOT NULL,
    validation_ok   BOOLEAN NOT NULL,
    rejection_reasons JSONB,
    executed        BOOLEAN NOT NULL,
    row_count       INTEGER,
    duration_ms     INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
