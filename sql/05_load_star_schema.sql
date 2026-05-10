-- Step 4: Load cleaned_unified_parking.csv into star schema
-- Prerequisite: run sql/01_star_schema_ddl.sql first.
--
-- Usage example (from project root):
-- psql -U postgres -d <your_db_name> -v csv_path="'/Users/chaitralikadam/Documents/DataMining_FinalProject/data/cleaned_unified_parking.csv'" -f sql/05_load_star_schema.sql
--
-- If csv_path is not passed, it defaults to: data/cleaned_unified_parking.csv

\set ON_ERROR_STOP on
\if :{?csv_path}
\else
\set csv_path '''data/cleaned_unified_parking.csv'''
\endif

BEGIN;

-- Rerun-safe load: clear fact first, then dimensions.
TRUNCATE TABLE parking_fact;
TRUNCATE TABLE time_dim;
TRUNCATE TABLE city_dim;
TRUNCATE TABLE location_dim;

-- Staging table exactly matching cleaned CSV columns.
DROP TABLE IF EXISTS stg_cleaned_unified_parking;
CREATE TEMP TABLE stg_cleaned_unified_parking (
    event_id TEXT,
    city TEXT,
    ts_start TIMESTAMP,
    ts_end TIMESTAMP,
    duration_minutes FLOAT,
    revenue FLOAT,
    location_id TEXT
);

-- Client-side copy from local CSV (works with psql).
\copy stg_cleaned_unified_parking (event_id, city, ts_start, ts_end, duration_minutes, revenue, location_id) FROM :csv_path WITH (FORMAT csv, HEADER true)

-- Defensive cleanup in staging (should already be clean from Step 2).
DELETE FROM stg_cleaned_unified_parking
WHERE ts_start IS NULL
   OR revenue IS NULL
   OR duration_minutes IS NULL
   OR location_id IS NULL
   OR city IS NULL
   OR revenue < 0
   OR duration_minutes < 0;

-- city_dim
INSERT INTO city_dim (city_name)
SELECT DISTINCT city
FROM stg_cleaned_unified_parking
ORDER BY city;

-- location_dim
INSERT INTO location_dim (location_id)
SELECT DISTINCT location_id
FROM stg_cleaned_unified_parking
ORDER BY location_id;

-- time_dim (one row per distinct ts_start)
INSERT INTO time_dim (ts, date, hour, day, month, year, weekday)
SELECT
    t.ts_start AS ts,
    t.ts_start::date AS date,
    EXTRACT(HOUR FROM t.ts_start)::INT AS hour,
    EXTRACT(DAY FROM t.ts_start)::INT AS day,
    EXTRACT(MONTH FROM t.ts_start)::INT AS month,
    EXTRACT(YEAR FROM t.ts_start)::INT AS year,
    EXTRACT(DOW FROM t.ts_start)::INT AS weekday
FROM (
    SELECT DISTINCT ts_start
    FROM stg_cleaned_unified_parking
) AS t
ORDER BY t.ts_start;

-- parking_fact
INSERT INTO parking_fact (time_id, location_id, city_id, revenue, duration_minutes, event_count)
SELECT
    td.time_id,
    s.location_id,
    cd.city_id,
    s.revenue,
    s.duration_minutes,
    1 AS event_count
FROM stg_cleaned_unified_parking AS s
JOIN time_dim AS td
    ON td.ts = s.ts_start
JOIN city_dim AS cd
    ON cd.city_name = s.city;

COMMIT;

-- Basic load audit
SELECT 'city_dim' AS table_name, COUNT(*) AS row_count FROM city_dim
UNION ALL
SELECT 'time_dim' AS table_name, COUNT(*) AS row_count FROM time_dim
UNION ALL
SELECT 'location_dim' AS table_name, COUNT(*) AS row_count FROM location_dim
UNION ALL
SELECT 'parking_fact' AS table_name, COUNT(*) AS row_count FROM parking_fact;
