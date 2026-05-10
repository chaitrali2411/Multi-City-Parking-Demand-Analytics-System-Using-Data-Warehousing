-- =============================================================================
-- STEP 6 (part A): ADDITIONAL INDEXES FOR OLAP / JOIN PATTERNS
--
-- Run after `01_star_schema_ddl.sql`. Uses IF NOT EXISTS for idempotency.
-- Re-run ANALYZE after bulk loads (see bottom).
-- =============================================================================

BEGIN;

-- Fact table: join/aggregate starting from time (trend queries, time windows)
CREATE INDEX IF NOT EXISTS idx_parking_fact_time_id ON parking_fact (time_id);

-- Fact table: city + location (underutilized-location style queries)
CREATE INDEX IF NOT EXISTS idx_parking_fact_city_location
    ON parking_fact (city_id, location_id);

-- Time dimension: hour-of-day slices (peak-hour dashboards)
CREATE INDEX IF NOT EXISTS idx_time_dim_hour_of_day ON time_dim (hour_of_day);

-- Time dimension: common range filters on calendar hierarchy
CREATE INDEX IF NOT EXISTS idx_time_dim_year_month_day
    ON time_dim (year_number, month_of_year, day_of_month);

-- Location: prefix / pattern filters (optional — btree still helps equality)
CREATE INDEX IF NOT EXISTS idx_location_dim_code_pattern
    ON location_dim (location_code varchar_pattern_ops);

COMMIT;

-- -----------------------------------------------------------------------------
-- Post-load maintenance (run manually or via scheduler after ETL)
-- -----------------------------------------------------------------------------
-- ANALYZE parking_fact;
-- ANALYZE time_dim;
-- ANALYZE location_dim;
-- ANALYZE city_dim;

-- =============================================================================
-- TUNING NOTES (logical / physical design — not executed SQL)
-- =============================================================================
-- 1) Rollup/Cube heavy queries: raise work_mem for the session if sorts spill:
--      SET work_mem = '256MB';
-- 2) Very large fact tables: consider BRIN on time_id or event_ts via time_dim
--    join pattern, or monthly partitioning on calendar_date carried to fact.
-- 3) Repeating dashboards: materialized view, e.g. revenue by month × city,
--    refreshed after nightly ETL (REFRESH MATERIALIZED VIEW CONCURRENTLY ...).
-- 4) If planner under-estimates ndistinct on joins, increase statistics target:
--      ALTER TABLE parking_fact ALTER COLUMN location_id SET STATISTICS 1000;
-- 5) After major loads, run VACUUM (ANALYZE) on fact + dimensions.
