"""
STEP 1: API DATA INGESTION — Multi-City Parking Demand Analysis

Fetches real records from open-data APIs with pagination, retry handling,
light schema alignment, and local raw persistence for downstream ETL.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Iterable
from urllib.request import urlopen
from urllib.parse import urlencode

import pandas as pd

# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Kept for downstream compatibility (step2 imports these constants/functions).
CHICAGO_CSV = DATA_DIR / "chicago_parking_meters.csv"
NYC_CSV = DATA_DIR / "nyc_parking.csv"
CHICAGO_FALLBACK = DATA_DIR / "sample_chicago_parking.csv"
NYC_FALLBACK = DATA_DIR / "sample_nyc_parking.csv"

# California source (San Francisco open data): parking meter transactions
CALIFORNIA_API_URL = "https://data.sfgov.org/resource/imvp-dq3v.csv"
NYC_API_URL = "https://data.cityofnewyork.us/resource/pvqr-7yc4.csv"
CHICAGO_API_CANDIDATES = [
    os.environ.get("CHICAGO_API_URL", "").strip(),
    os.environ.get("CALIFORNIA_API_URL", "").strip(),
    CALIFORNIA_API_URL,
]

# Required config knobs for controlled ingestion.
TOTAL_ROWS = 100_000  # Set smaller for quick tests; None means fetch all available.
CHUNK_SIZE = 50_000
OUTPUT_PATH = DATA_DIR / "raw"

CHICAGO_RAW_OUT = OUTPUT_PATH / "chicago_raw.csv"
NYC_RAW_OUT = OUTPUT_PATH / "nyc_raw.csv"

RETRY_COUNT = 3
RETRY_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("step1_data_ingestion")


def _resolve_path(primary: Path, fallback: Path) -> Path:
    """Legacy helper used by downstream steps."""
    if primary.exists():
        return primary
    if fallback.exists():
        LOGGER.warning("Using fallback sample file: %s", fallback.name)
        return fallback
    raise FileNotFoundError(f"Missing {primary} and fallback {fallback}")


def load_csv(path: Path, city_label: str) -> pd.DataFrame:
    """Legacy helper used by downstream steps."""
    df = pd.read_csv(path, encoding="utf-8")
    df.attrs["source_file"] = str(path)
    df.attrs["city_label"] = city_label
    return df


def _pick_first_existing(df: pd.DataFrame, candidates: Iterable[str]) -> pd.Series:
    """Return first matching column from candidates, else all-NA series."""
    for col in candidates:
        if col in df.columns:
            return df[col]
    return pd.Series([pd.NA] * len(df), index=df.index, dtype="object")


def _fetch_paginated_csv(base_url: str, total_rows: int | None, chunk_size: int) -> pd.DataFrame:
    """Fetch API data using $limit/$offset paging and retry on failures."""
    chunks: list[pd.DataFrame] = []
    offset = 0
    fetched = 0

    while True:
        remaining = None if total_rows is None else total_rows - fetched
        if remaining is not None and remaining <= 0:
            break
        limit = chunk_size if remaining is None else min(chunk_size, remaining)
        params = {"$limit": limit, "$offset": offset}
        url = f"{base_url}?{urlencode(params)}"

        last_err: Exception | None = None
        chunk: pd.DataFrame | None = None
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                chunk = pd.read_csv(url, low_memory=False, encoding="utf-8")
                break
            except Exception as exc:  # broad catch to handle network/parser issues
                last_err = exc
                LOGGER.warning(
                    "Fetch failed (attempt %s/%s) for offset=%s limit=%s: %s",
                    attempt,
                    RETRY_COUNT,
                    offset,
                    limit,
                    exc,
                )
                if attempt < RETRY_COUNT:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        if chunk is None:
            raise RuntimeError(f"API fetch failed after retries for {url}") from last_err
        if chunk.empty:
            LOGGER.info("No more rows from API at offset=%s; stopping.", offset)
            break

        chunks.append(chunk)
        fetched += len(chunk)
        offset += len(chunk)
        LOGGER.info("Fetched chunk rows=%s | total_fetched=%s", len(chunk), fetched)

        if len(chunk) < limit:
            break

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def _is_endpoint_reachable(base_url: str) -> bool:
    """Check endpoint health with a tiny query before full pagination."""
    if not base_url:
        return False
    probe_url = f"{base_url}?{urlencode({'$limit': 1, '$offset': 0})}"
    try:
        with urlopen(probe_url, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return int(resp.status) == 200
    except Exception:
        return False


def _first_reachable_url(url_candidates: list[str]) -> str | None:
    for candidate in url_candidates:
        if _is_endpoint_reachable(candidate):
            return candidate
    return None


def fetch_chicago_data(total_rows: int | None = TOTAL_ROWS, chunk_size: int = CHUNK_SIZE) -> pd.DataFrame:
    """
    Fetch California (SF) parking meter transactions and map to the existing
    Chicago-like schema expected by downstream Step 2:
      transmission_datetime -> TRANSACTION_ID
      post_id               -> METER_ID / POST_ID
      session_start_dt      -> TRANSACTION_START
      session_end_dt        -> TRANSACTION_END
      gross_paid_amt        -> AMOUNT_PAID
      payment_type          -> PAYMENT_TYPE
    """
    chosen_url = _first_reachable_url(CHICAGO_API_CANDIDATES)
    if not chosen_url:
        if CHICAGO_FALLBACK.exists():
            LOGGER.error(
                "No reachable California API endpoint found. Falling back to %s",
                CHICAGO_FALLBACK,
            )
            return pd.read_csv(CHICAGO_FALLBACK, encoding="utf-8")
        raise RuntimeError(
            "No reachable California API endpoint. "
            "Set CALIFORNIA_API_URL (or CHICAGO_API_URL legacy override) "
            "to a valid Socrata CSV endpoint."
        )

    raw = _fetch_paginated_csv(chosen_url, total_rows=total_rows, chunk_size=chunk_size)
    if raw.empty:
        LOGGER.warning("California API returned zero rows.")
        return raw

    tx_id = _pick_first_existing(raw, ["transmission_datetime", "transaction_id"])
    meter = _pick_first_existing(raw, ["post_id", "meter_id", "meter_number", "meter"])
    start = _pick_first_existing(raw, ["session_start_dt", "transaction_start"])
    end = _pick_first_existing(raw, ["session_end_dt", "transaction_end"])
    amount = _pick_first_existing(raw, ["gross_paid_amt", "amount_paid", "amount"])
    pay_type = _pick_first_existing(raw, ["payment_type"])

    # Keep downstream compatibility by exporting the Chicago-style columns.
    out = pd.DataFrame(index=raw.index)
    out["TRANSACTION_ID"] = tx_id.astype("string")
    out["METER_ID"] = meter.astype("string")
    out["TRANSACTION_START"] = start.astype("string")
    out["TRANSACTION_END"] = end.astype("string")
    out["AMOUNT_PAID"] = pd.to_numeric(amount, errors="coerce")
    out["PAYMENT_TYPE"] = pay_type.astype("string")
    out["POST_ID"] = meter.astype("string")
    out["city"] = "California"
    return out


def _parse_violation_time(series: pd.Series) -> pd.Series:
    """Parse NYC violation time formats like 0930A / 1145P into HH:MM."""
    s = series.astype("string").str.strip().str.upper()
    # Keep first 4 digits and optional meridiem letter.
    m = s.str.extract(r"^(?P<hhmm>\d{3,4})(?P<ap>[AP]?)")
    hhmm = m["hhmm"].fillna("")
    ap = m["ap"].fillna("")
    hhmm = hhmm.str.zfill(4)
    hh = pd.to_numeric(hhmm.str[:2], errors="coerce")
    mm = pd.to_numeric(hhmm.str[2:], errors="coerce")
    valid = hh.between(0, 23) & mm.between(0, 59)
    hh = hh.where(valid)
    mm = mm.where(valid)
    hh = hh.where(ap == "", (hh % 12) + (ap == "P") * 12)
    return (
        hh.astype("Int64").astype("string").str.zfill(2)
        + ":"
        + mm.astype("Int64").astype("string").str.zfill(2)
        + ":00"
    )


def fetch_nyc_data(total_rows: int | None = TOTAL_ROWS, chunk_size: int = CHUNK_SIZE) -> pd.DataFrame:
    """
    Fetch NYC parking violations and align core fields:
      issue_date + violation_time -> ts_start
      fine_amount -> revenue
      street_name -> location_id
    """
    raw = _fetch_paginated_csv(NYC_API_URL, total_rows=total_rows, chunk_size=chunk_size)
    if raw.empty:
        LOGGER.warning("NYC API returned zero rows.")
        return raw

    issue_date = _pick_first_existing(raw, ["issue_date"])
    violation_time = _pick_first_existing(raw, ["violation_time"])
    fine_amount = _pick_first_existing(raw, ["fine_amount", "payment_amount"])
    street_name = _pick_first_existing(raw, ["street_name", "violation_location"])

    issue_ts = pd.to_datetime(issue_date, errors="coerce")
    time_text = _parse_violation_time(violation_time)
    combined_ts = pd.to_datetime(
        issue_ts.dt.strftime("%Y-%m-%d").fillna("") + " " + time_text.fillna("00:00:00"),
        errors="coerce",
    )

    out = raw.copy()
    out["ts_start"] = combined_ts
    out["revenue"] = pd.to_numeric(fine_amount, errors="coerce")
    out["location_id"] = street_name.astype("string")
    out["city"] = "NYC"
    return out


def save_raw_data(df: pd.DataFrame, output_file: Path) -> None:
    """Save raw aligned data to local CSV."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)
    LOGGER.info("Saved %s rows to %s", len(df), output_file)


def inspect_dataframe(name: str, df: pd.DataFrame) -> None:
    """Log schema snapshot for validation."""
    LOGGER.info("%s | shape=%s", name, df.shape)
    LOGGER.info("%s | dtypes:\n%s", name, df.dtypes.to_string())
    missing = df.isna().sum()
    missing = missing[missing > 0]
    if missing.empty:
        LOGGER.info("%s | missing: none", name)
    else:
        LOGGER.info("%s | missing counts:\n%s", name, missing.to_string())


def main() -> None:
    LOGGER.info(
        "Starting API ingestion with TOTAL_ROWS=%s CHUNK_SIZE=%s OUTPUT_PATH=%s",
        TOTAL_ROWS,
        CHUNK_SIZE,
        OUTPUT_PATH,
    )
    chicago_df = fetch_chicago_data()
    nyc_df = fetch_nyc_data()

    save_raw_data(chicago_df, CHICAGO_RAW_OUT)
    save_raw_data(nyc_df, NYC_RAW_OUT)

    # Minimal downstream compatibility: keep canonical paths updated too.
    save_raw_data(chicago_df, CHICAGO_CSV)
    save_raw_data(nyc_df, NYC_CSV)

    inspect_dataframe("California API raw", chicago_df)
    inspect_dataframe("NYC API raw", nyc_df)
    LOGGER.info("Step 1 complete: API ingestion + raw persistence done.")


if __name__ == "__main__":
    main()
