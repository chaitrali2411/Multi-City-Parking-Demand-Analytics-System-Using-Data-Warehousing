# Multi-City Parking Demand Analytics (Data Warehousing)

This repository implements an **end-to-end data warehousing workflow** for comparing parking-related activity across two jurisdictions: **California (San Francisco)** open-data parking meter transactions and **New York City** open-data parking violations. The pipeline covers **API ingestion**, **cleaning and unified schema design**, a **PostgreSQL star schema**, **batch ETL**, **OLAP-style SQL** (including rollups), and **dashboard-style visualizations**.

---

## What you will find here

| Stage | Role |
|-------|------|
| Ingestion | Paginated fetch from public APIs; saves canonical CSVs under `data/`. |
| Cleaning | Builds one unified fact-level CSV plus hourly and daily aggregates. |
| Warehouse | Star schema DDL (`city_dim`, `time_dim`, `location_dim`, `parking_fact`). |
| ETL | Loads the cleaned CSV into PostgreSQL with dimension upserts. |
| Analytics | SQL file with OLAP-oriented queries on the loaded star schema. |
| Visualization | Matplotlib, Seaborn, and Plotly figures plus short interpretation notes. |

---

## Data sources and naming

- **California (SF):** San Francisco parking meter transaction data (open data API).  
- **NYC:** NYC parking violation records (open data API).

Some **file paths and internal names are legacy** for compatibility across pipeline steps—for example `chicago_parking_meters.csv` and `sample_chicago_parking.csv` refer to the **California/SF–aligned** meter schema produced by ingestion, **not** Chicago data.

---

## Prerequisites

- **Python** 3.10+ recommended.
- **Internet access** for ingestion (live API calls). If APIs are unreachable, ingestion can fall back to sample CSVs when present (see `src/data_ingestion.py`).
- **PostgreSQL** for DDL, ETL, and OLAP SQL. Ingestion, cleaning, and dashboards can be run using files only; the database is required for the warehouse and OLAP queries.

---

## Repository layout

| Path | Description |
|------|-------------|
| `src/data_ingestion.py` | Fetches API data; writes raw and canonical CSVs under `data/`. |
| `src/cleaning_preprocessing.py` | Produces unified cleaned data and hourly/daily summaries. |
| `sql/01_star_schema_ddl.sql` | Creates the star schema in PostgreSQL. |
| `src/etl_load.py` | Batch loads `cleaned_unified_parking.csv` into the warehouse. |
| `sql/02_olap_queries.sql` | OLAP-oriented analysis queries (e.g. `ROLLUP`, `CUBE`). |
| `sql/03_performance_indexes.sql` | Optional extra indexes (review column names against your DDL before running). |
| `sql/04_explain_templates.sql` | Optional `EXPLAIN` templates for query plans. |
| `sql/05_load_star_schema.sql` | Optional alternative: bulk load via `psql` instead of the Python ETL. |
| `src/visual_dashboards.py` | Generates figures under `outputs/figures/` and refreshes `INSIGHTS.md`. |
| `data/` | Inputs and generated CSVs from the pipeline. |
| `outputs/figures/` | Generated PNG/HTML dashboards and notes. |

---

## Setup

From the **project root** (the folder that contains `src/` and `data/`):

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## How to run the pipeline (order)

Run commands from the **project root**. Python scripts add `src/` to the path when executed as shown.

| Step | Command | Main outputs |
|------|---------|----------------|
| **1 — Ingest** | `python src/data_ingestion.py` | `data/chicago_parking_meters.csv` (California/SF), `data/nyc_parking.csv`, optional `data/raw/*.csv` |
| **2 — Clean** | `python src/cleaning_preprocessing.py` | `data/cleaned_unified_parking.csv`, `data/summary_hourly.csv`, `data/summary_daily.csv` |
| **3 — DDL** | Apply in PostgreSQL: `psql ... -f sql/01_star_schema_ddl.sql` | Tables: `city_dim`, `time_dim`, `location_dim`, `parking_fact` |
| **4 — ETL** | Set connection env vars (below), then `python src/etl_load.py` | Rows loaded into `parking_fact` and dimensions |
| **5 — OLAP** | `psql ... -f sql/02_olap_queries.sql` | Query results in your SQL session |
| **7 — Charts** | `python src/visual_dashboards.py` | PNG/HTML in `outputs/figures/`, plus `INSIGHTS.md` |

Stages 3 and 5 use SQL only (no separate Python modules). Python modules are named by role (`data_ingestion`, `cleaning_preprocessing`, etc.), not by step number.

---

## Environment variables (database and ETL)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Preferred. Example: `postgresql://user:password@localhost:5432/your_db` |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | Used if `DATABASE_URL` is not set (defaults in code assume local Postgres). |
| `PDM_LOAD_MODE` | `replace` (default): delete existing fact rows before load. `append`: keep existing facts (reloads may duplicate). |

Optional ingestion overrides (see `src/data_ingestion.py`): `CALIFORNIA_API_URL` or legacy `CHICAGO_API_URL` to point at a Socrata-style CSV endpoint for the California/SF feed.

---

## Dependencies

All Python packages are listed in **`requirements.txt`** with short comments explaining each role. Install with `pip install -r requirements.txt`.

---

## Reproducibility notes for grading

- Running ingestion against live APIs may yield **different row counts** over time; the pipeline logic and schema remain the same.
- For a **fixed snapshot**, commit or supply the CSVs under `data/` after a successful run, then cleaning onward can be replayed without calling the APIs again.
