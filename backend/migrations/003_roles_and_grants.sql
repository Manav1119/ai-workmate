-- 003: least-privilege grants. Roles are created by scripts/bootstrap_db.py.

-- Nobody gets implicit access through PUBLIC.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON SCHEMA analytics FROM PUBLIC;

-- Application role: full DML on app schema, DML on analytics for CSV imports.
GRANT USAGE ON SCHEMA app, analytics TO workmate_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO workmate_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO workmate_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.campaigns, analytics.campaign_daily_metrics TO workmate_app;

-- Read-only role: SELECT on the two approved analytics tables. Nothing else.
GRANT USAGE ON SCHEMA analytics TO workmate_reader;
GRANT SELECT ON analytics.campaigns, analytics.campaign_daily_metrics TO workmate_reader;
REVOKE ALL ON SCHEMA app FROM workmate_reader;
ALTER ROLE workmate_reader SET default_transaction_read_only = on;
ALTER ROLE workmate_reader SET statement_timeout = '5s';
ALTER ROLE workmate_reader SET search_path = analytics;

-- RLS policies
DROP POLICY IF EXISTS reader_dataset_campaigns ON analytics.campaigns;
CREATE POLICY reader_dataset_campaigns ON analytics.campaigns FOR SELECT TO workmate_reader
    USING (dataset_id = NULLIF(current_setting('app.dataset_id', true), '')::int);
DROP POLICY IF EXISTS reader_dataset_metrics ON analytics.campaign_daily_metrics;
CREATE POLICY reader_dataset_metrics ON analytics.campaign_daily_metrics FOR SELECT TO workmate_reader
    USING (dataset_id = NULLIF(current_setting('app.dataset_id', true), '')::int);

DROP POLICY IF EXISTS app_all_campaigns ON analytics.campaigns;
CREATE POLICY app_all_campaigns ON analytics.campaigns FOR ALL TO workmate_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS app_all_metrics ON analytics.campaign_daily_metrics;
CREATE POLICY app_all_metrics ON analytics.campaign_daily_metrics FOR ALL TO workmate_app USING (true) WITH CHECK (true);
