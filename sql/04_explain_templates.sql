-- =============================================================================
-- STEP 6 (part B): EXPLAIN TEMPLATES FOR KEY OLAP SHAPES
--
-- Default uses EXPLAIN (costs, verbose) — fast, no execution.
-- For real timings & buffer hits on production-like data, switch to:
--   EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT)
--
-- Run: psql -d parking_dw -f sql/04_explain_templates.sql
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A) Hourly demand join path (fact → time → city)
-- -----------------------------------------------------------------------------
EXPLAIN (COSTS, VERBOSE, FORMAT TEXT)
SELECT
    cd.city_name,
    td.hour_of_day,
    SUM(pf.occupancy_count) AS demand_events
FROM parking_fact AS pf
JOIN time_dim AS td ON td.time_id = pf.time_id
JOIN city_dim AS cd ON cd.city_id = pf.city_id
GROUP BY cd.city_name, td.hour_of_day;


-- -----------------------------------------------------------------------------
-- B) Revenue rollup (fact → time → city) — sort/hash aggregate cost visible
-- -----------------------------------------------------------------------------
EXPLAIN (COSTS, VERBOSE, FORMAT TEXT)
SELECT
    td.calendar_date,
    cd.city_name,
    SUM(pf.revenue) AS revenue,
    GROUPING(td.calendar_date) AS g_date,
    GROUPING(cd.city_name) AS g_city
FROM parking_fact AS pf
JOIN time_dim AS td ON td.time_id = pf.time_id
JOIN city_dim AS cd ON cd.city_id = pf.city_id
GROUP BY ROLLUP (td.calendar_date, cd.city_name);


-- -----------------------------------------------------------------------------
-- C) Location intensity (fact → location → city)
-- -----------------------------------------------------------------------------
EXPLAIN (COSTS, VERBOSE, FORMAT TEXT)
SELECT
    cd.city_name,
    ld.location_code,
    SUM(pf.occupancy_count) AS events
FROM parking_fact AS pf
JOIN location_dim AS ld ON ld.location_id = pf.location_id
JOIN city_dim AS cd ON cd.city_id = pf.city_id
GROUP BY cd.city_name, ld.location_code;


-- -----------------------------------------------------------------------------
-- D) CUBE city × hour (large grouping set — watch aggregate memory)
-- -----------------------------------------------------------------------------
EXPLAIN (COSTS, VERBOSE, FORMAT TEXT)
SELECT
    cd.city_name,
    td.hour_of_day,
    SUM(pf.occupancy_count) AS demand_events,
    GROUPING(cd.city_name) AS g_city,
    GROUPING(td.hour_of_day) AS g_hour
FROM parking_fact AS pf
JOIN time_dim AS td ON td.time_id = pf.time_id
JOIN city_dim AS cd ON cd.city_id = pf.city_id
GROUP BY CUBE (cd.city_name, td.hour_of_day);


-- =============================================================================
-- OPTIONAL: swap in EXPLAIN (ANALYZE, BUFFERS) for the statements above when
-- you want measured runtime and buffer usage (executes each query once).
-- =============================================================================
