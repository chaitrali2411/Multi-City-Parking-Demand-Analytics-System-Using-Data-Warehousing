-- Step 3 Star Schema DDL (PostgreSQL)
-- Compatible with cleaned_unified_parking.csv

BEGIN;

-- Rerun safety: drop fact first due to FK dependencies.
DROP TABLE IF EXISTS parking_fact;
DROP TABLE IF EXISTS time_dim;
DROP TABLE IF EXISTS city_dim;
DROP TABLE IF EXISTS location_dim;

-- 1) City dimension
CREATE TABLE city_dim (
    city_id SERIAL PRIMARY KEY,
    city_name TEXT NOT NULL UNIQUE
);

-- 2) Time dimension
CREATE TABLE time_dim (
    time_id SERIAL PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    date DATE NOT NULL,
    hour INT NOT NULL CHECK (hour BETWEEN 0 AND 23),
    day INT NOT NULL CHECK (day BETWEEN 1 AND 31),
    month INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year INT NOT NULL,
    weekday INT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    UNIQUE (ts)
);

-- 3) Location dimension
CREATE TABLE location_dim (
    location_id TEXT PRIMARY KEY
);

-- 4) Fact table
CREATE TABLE parking_fact (
    fact_id SERIAL PRIMARY KEY,
    time_id INT NOT NULL REFERENCES time_dim (time_id),
    location_id TEXT NOT NULL REFERENCES location_dim (location_id),
    city_id INT NOT NULL REFERENCES city_dim (city_id),
    revenue FLOAT NOT NULL CHECK (revenue >= 0),
    duration_minutes FLOAT NOT NULL CHECK (duration_minutes >= 0),
    event_count INT NOT NULL DEFAULT 1
);

-- Required indexes for OLAP query performance
CREATE INDEX idx_parking_fact_time_id ON parking_fact (time_id);
CREATE INDEX idx_parking_fact_city_id ON parking_fact (city_id);
CREATE INDEX idx_parking_fact_location_id ON parking_fact (location_id);
CREATE INDEX idx_time_dim_date ON time_dim (date);
CREATE INDEX idx_time_dim_hour ON time_dim (hour);

COMMIT;
