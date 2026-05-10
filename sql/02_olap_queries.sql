-- ============================================================================
-- 02_olap_queries.sql
-- PostgreSQL OLAP analysis on:
--   parking_fact(time_id, location_id, city_id, revenue, duration_minutes, event_count)
--   time_dim(time_id, ts, date, hour, day, month, year)
--   city_dim(city_id, city_name)
--   location_dim(location_id)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) PEAK DEMAND HOURS PER CITY
-- Goal:
--   Find the busiest hour for each city using COUNT(event_count), then rank
--   each city's hours from highest to lowest demand.
-- Notes:
--   COUNT(event_count) is used exactly as requested (event_count is non-null).
-- ---------------------------------------------------------------------------
WITH hourly_city_demand AS (
    SELECT
        c.city_name,
        t.hour,
        COUNT(f.event_count) AS demand_events
    FROM parking_fact f
    JOIN time_dim t
        ON f.time_id = t.time_id
    JOIN city_dim c
        ON f.city_id = c.city_id
    GROUP BY c.city_name, t.hour
),
ranked_hours AS (
    SELECT
        city_name,
        hour,
        demand_events,
        RANK() OVER (
            PARTITION BY city_name
            ORDER BY demand_events DESC, hour ASC
        ) AS demand_rank
    FROM hourly_city_demand
)
SELECT
    city_name,
    hour AS peak_hour,
    demand_events
FROM ranked_hours
WHERE demand_rank = 1
ORDER BY demand_events DESC, city_name;


-- ---------------------------------------------------------------------------
-- 2) REVENUE OVER TIME (DAILY) WITH ROLLUP
-- Goal:
--   Show daily revenue by city and include subtotals + grand total.
-- ROLLUP(date, city_name) levels:
--   (date, city) -> detail rows
--   (date, NULL) -> subtotal per date (all cities)
--   (NULL, NULL) -> grand total
-- ---------------------------------------------------------------------------
SELECT
    t.date,
    c.city_name,
    SUM(f.revenue) AS total_revenue,
    CASE
        WHEN GROUPING(t.date) = 1 AND GROUPING(c.city_name) = 1 THEN 'GRAND_TOTAL'
        WHEN GROUPING(c.city_name) = 1 THEN 'DATE_SUBTOTAL'
        ELSE 'DETAIL'
    END AS row_level
FROM parking_fact f
JOIN time_dim t
    ON f.time_id = t.time_id
JOIN city_dim c
    ON f.city_id = c.city_id
GROUP BY ROLLUP (t.date, c.city_name)
ORDER BY
    t.date NULLS LAST,
    c.city_name NULLS LAST;


-- ---------------------------------------------------------------------------
-- 3) UNDERUTILIZED LOCATIONS (BOTTOM 10 PER CITY)
-- Goal:
--   Compute total events per location and show lowest-usage 10 locations
--   inside each city.
-- ---------------------------------------------------------------------------
WITH location_usage AS (
    SELECT
        c.city_name,
        f.location_id,
        SUM(f.event_count) AS total_events,
        SUM(f.revenue) AS total_revenue
    FROM parking_fact f
    JOIN city_dim c
        ON f.city_id = c.city_id
    JOIN location_dim l
        ON f.location_id = l.location_id
    GROUP BY c.city_name, f.location_id
),
ranked_locations AS (
    SELECT
        city_name,
        location_id,
        total_events,
        total_revenue,
        ROW_NUMBER() OVER (
            PARTITION BY city_name
            ORDER BY total_events ASC, location_id ASC
        ) AS rn
    FROM location_usage
)
SELECT
    city_name,
    location_id,
    total_events,
    total_revenue
FROM ranked_locations
WHERE rn <= 10
ORDER BY city_name, total_events ASC, location_id;


-- ---------------------------------------------------------------------------
-- 4) CITY COMPARISON
-- Goal:
--   Compare cities by:
--     - total events
--     - total revenue
--     - average duration
-- ---------------------------------------------------------------------------
SELECT
    c.city_name,
    SUM(f.event_count) AS total_events,
    SUM(f.revenue) AS total_revenue,
    AVG(f.duration_minutes) AS avg_duration_minutes
FROM parking_fact f
JOIN city_dim c
    ON f.city_id = c.city_id
GROUP BY c.city_name
ORDER BY total_revenue DESC, total_events DESC;


-- ---------------------------------------------------------------------------
-- 5) MULTI-DIMENSIONAL ANALYSIS WITH CUBE(city_name, hour)
-- Goal:
--   Show demand variation across city and hour, including all subtotal levels.
-- CUBE levels include:
--   (city, hour), (city, ALL_HOURS), (ALL_CITIES, hour), (ALL_CITIES, ALL_HOURS)
-- ---------------------------------------------------------------------------
SELECT
    c.city_name,
    t.hour,
    SUM(f.event_count) AS total_events,
    SUM(f.revenue) AS total_revenue,
    AVG(f.duration_minutes) AS avg_duration_minutes,
    GROUPING(c.city_name) AS g_city,
    GROUPING(t.hour) AS g_hour
FROM parking_fact f
JOIN city_dim c
    ON f.city_id = c.city_id
JOIN time_dim t
    ON f.time_id = t.time_id
GROUP BY CUBE (c.city_name, t.hour)
ORDER BY
    c.city_name NULLS LAST,
    t.hour NULLS LAST;


-- ============================================================================
-- Brief interpretation guide
-- 1) Peak demand hours per city:
--    Identifies each city's highest-traffic hour (best for staffing/pricing).
--
-- 2) Revenue over time with ROLLUP:
--    Shows daily city revenue plus date-level and overall totals in one query.
--
-- 3) Underutilized locations:
--    Lists bottom-10 low-usage locations per city for optimization actions.
--
-- 4) City comparison:
--    Side-by-side city KPI view for demand, monetization, and parking duration.
--
-- 5) CUBE analysis:
--    Provides city-hour detail and all subtotal combinations for OLAP slicing.
-- ============================================================================
