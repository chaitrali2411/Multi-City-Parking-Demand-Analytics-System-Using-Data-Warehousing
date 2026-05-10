"""
STEP 4: LOAD CLEANED DATA INTO POSTGRESQL (batch ETL)

Reads `data/cleaned_unified_parking.csv` from Step 2, upserts dimensions, then
batch-inserts `parking_fact` rows.

Prerequisites:
  - Run `sql/01_star_schema_ddl.sql` against your database first.
  - Connection via `DATABASE_URL` (preferred) or `PGHOST`, `PGPORT`, `PGUSER`,
    `PGPASSWORD`, `PGDATABASE`.

Environment:
  - `DATABASE_URL` — e.g. postgresql://user:pass@localhost:5432/parking_dw
  - `PDM_LOAD_MODE` — `replace` (default): DELETE all fact rows before load;
    `append`: keep existing facts (may duplicate if same events reloaded).

Run from project root:
  python src/step4_etl_load.py
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from step1_data_ingestion import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
CLEAN_CSV = DATA_DIR / "cleaned_unified_parking.csv"

BATCH_SIZE = 500


def _connect():
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
        dbname=os.environ.get("PGDATABASE", "parking_db"),
    )


def _time_dim_row(ts: pd.Timestamp) -> tuple[Any, ...]:
    """One full row for time_dim aligned to sql/01_star_schema_ddl.sql."""
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    event_ts = ts.to_pydatetime()
    cal = ts.date()
    hour = int(ts.hour)
    weekday = int(ts.weekday())  # 0=Mon .. 6=Sun
    return (
        event_ts,
        cal,
        hour,
        int(ts.day),
        int(ts.month),
        int(ts.year),
        weekday,
    )


def ensure_cities(cur, cities: list[str]) -> None:
    uniq = sorted({str(c).strip() for c in cities if str(c).strip()})
    if not uniq:
        return
    rows = [(c,) for c in uniq]
    execute_values(
        cur,
        """
        INSERT INTO city_dim (city_name) VALUES %s
        ON CONFLICT (city_name) DO NOTHING;
        """,
        rows,
        page_size=BATCH_SIZE,
    )


def load_city_map(cur) -> dict[str, int]:
    cur.execute("SELECT city_id, city_name FROM city_dim;")
    return {row[1]: row[0] for row in cur.fetchall()}


def upsert_time_dimension(cur, timestamps: list[pd.Timestamp]) -> None:
    rows = []
    seen: set[pd.Timestamp] = set()
    for raw in timestamps:
        ts = pd.Timestamp(raw)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        ts_norm = ts.floor("s")  # drop sub-second noise if any
        if ts_norm in seen:
            continue
        seen.add(ts_norm)
        rows.append(_time_dim_row(ts_norm))

    if not rows:
        return

    execute_values(
        cur,
        """
        INSERT INTO time_dim (ts, date, hour, day, month, year, weekday)
        VALUES %s
        ON CONFLICT (ts) DO NOTHING
        """,
        rows,
        page_size=BATCH_SIZE,
    )


def load_time_map(cur, timestamps: list[pd.Timestamp]) -> dict[pd.Timestamp, int]:
    uniq = sorted({pd.Timestamp(t).floor("s") for t in timestamps})
    if not uniq:
        return {}
    as_dt = [pd.Timestamp(t).to_pydatetime() for t in uniq]
    cur.execute(
        "SELECT time_id, ts FROM time_dim WHERE ts = ANY(%s);",
        (as_dt,),
    )
    out: dict[pd.Timestamp, int] = {}
    for time_id, ts in cur.fetchall():
        out[pd.Timestamp(ts).floor("s")] = int(time_id)
    return out


def upsert_location_dimension(cur, codes: list[str]) -> None:
    rows = []
    seen: set[str] = set()
    for code in codes:
        c = str(code).strip()
        if not c or c in seen:
            continue
        seen.add(c)
        rows.append((c,))

    if not rows:
        return

    execute_values(
        cur,
        """
        INSERT INTO location_dim (location_id)
        VALUES %s
        ON CONFLICT (location_id) DO NOTHING
        """,
        rows,
        page_size=BATCH_SIZE,
    )


def load_location_map(cur, codes: list[str]) -> dict[str, int]:
    uniq = sorted({str(c).strip() for c in codes if str(c).strip()})
    if not uniq:
        return {}
    cur.execute(
        "SELECT location_id FROM location_dim WHERE location_id = ANY(%s);",
        (uniq,),
    )
    return {str(row[0]): str(row[0]) for row in cur.fetchall()}


def clear_facts_if_replace(cur, mode: str) -> None:
    if mode == "replace":
        cur.execute("DELETE FROM parking_fact;")


def insert_facts_batch(cur, fact_rows: list[tuple]) -> None:
    if not fact_rows:
        return
    execute_values(
        cur,
        """
        INSERT INTO parking_fact (
            time_id, location_id, city_id, revenue, duration_minutes, event_count
        ) VALUES %s
        """,
        fact_rows,
        page_size=BATCH_SIZE,
    )


def main() -> None:
    if not CLEAN_CSV.exists():
        raise FileNotFoundError(
            f"Missing {CLEAN_CSV}. Run step2_cleaning_preprocessing.py first."
        )

    df = pd.read_csv(CLEAN_CSV, parse_dates=["ts_start", "ts_end"])
    mode = os.environ.get("PDM_LOAD_MODE", "replace").lower()

    conn = _connect()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            ensure_cities(cur, df["city"].astype(str).tolist())
            city_map = load_city_map(cur)

            ts_list = df["ts_start"].tolist()
            upsert_time_dimension(cur, ts_list)
            time_map = load_time_map(cur, ts_list)

            loc_list = df["location_id"].tolist()
            upsert_location_dimension(cur, loc_list)
            loc_map = load_location_map(cur, loc_list)

            clear_facts_if_replace(cur, mode)

            missing_city = set(df["city"].unique()) - set(city_map.keys())
            if missing_city:
                raise ValueError(
                    f"Unknown city names in CSV (add to city_dim): {missing_city}"
                )

            fact_rows: list[tuple] = []
            for _, row in df.iterrows():
                ts = pd.Timestamp(row["ts_start"]).floor("s")
                tid = time_map.get(ts)
                lid = loc_map.get(str(row["location_id"]).strip())
                cid = city_map[row["city"]]
                if tid is None or lid is None:
                    raise RuntimeError(
                        f"Missing dimension key for row event_id={row.get('event_id')}: "
                        f"time_id={tid}, location_id={lid}"
                    )
                rev = Decimal(str(row["revenue"]))
                dur = row["duration_minutes"]
                dur_dec = None if pd.isna(dur) else Decimal(str(float(dur)))
                fact_rows.append((tid, lid, cid, rev, dur_dec, 1))

            insert_facts_batch(cur, fact_rows)

        conn.commit()
        print(
            f"ETL complete: loaded {len(fact_rows)} fact rows "
            f"(mode={mode}, batch_size={BATCH_SIZE})."
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
