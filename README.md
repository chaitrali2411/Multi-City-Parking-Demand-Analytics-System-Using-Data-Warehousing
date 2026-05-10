# Multi-City Parking Demand Analytics (Data Warehousing)

End-to-end pipeline: API ingestion → cleaning → PostgreSQL star schema → ETL → OLAP SQL → dashboards.

## Repository layout

| Path | Description |
|------|-------------|
| `src/step1_data_ingestion.py` | Fetch and save raw/canonical CSVs |
| `src/step2_cleaning_preprocessing.py` | Unified clean dataset + hourly/daily summaries |
| `sql/01_star_schema_ddl.sql` | Star schema DDL |
| `src/step4_etl_load.py` | Batch load into PostgreSQL |
| `sql/02_olap_queries.sql` | OLAP queries (ROLLUP, CUBE) |
| `src/step7_visual_dashboards.py` | Figures + `outputs/figures/INSIGHTS.md` |
| `data/` | Input/output CSVs |
| `outputs/figures/` | Generated PNG/HTML |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (order)

1. `python src/step1_data_ingestion.py`
2. `python src/step2_cleaning_preprocessing.py`
3. Apply `sql/01_star_schema_ddl.sql` in PostgreSQL
4. Set `DATABASE_URL` or `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`, then `python src/step4_etl_load.py`
5. `psql ... -f sql/02_olap_queries.sql`
6. `python src/step7_visual_dashboards.py`

## Dependencies

See `requirements.txt`.
