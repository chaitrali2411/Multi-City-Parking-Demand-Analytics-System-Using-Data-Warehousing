"""
DATA CLEANING & PREPROCESSING

Builds a unified cleaned dataset from:
- data/chicago_parking_meters.csv
- data/nyc_parking.csv

And writes:
- data/cleaned_unified_parking.csv
- data/summary_hourly.csv
- data/summary_daily.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Keep paths explicit and unchanged as requested.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHICAGO_INPUT = DATA_DIR / "chicago_parking_meters.csv"
NYC_INPUT = DATA_DIR / "nyc_parking.csv"

CLEANED_OUTPUT = DATA_DIR / "cleaned_unified_parking.csv"
HOURLY_OUTPUT = DATA_DIR / "summary_hourly.csv"
DAILY_OUTPUT = DATA_DIR / "summary_daily.csv"

UNIFIED_COLUMNS = [
    "event_id",
    "city",
    "ts_start",
    "ts_end",
    "duration_minutes",
    "revenue",
    "location_id",
]


def _pick_first_existing(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """Return the first existing column from candidates; otherwise NA series."""
    for col in candidates:
        if col in df.columns:
            return df[col]
    return pd.Series([pd.NA] * len(df), index=df.index, dtype="object")


def _parse_nyc_violation_time(series: pd.Series) -> pd.Series:
    """
    Parse NYC violation time values like 0930A / 1145P to HH:MM:SS.
    Invalid values become NaN (and later default to 00:00:00 for combining).
    """
    s = series.astype("string").str.strip().str.upper()
    m = s.str.extract(r"^(?P<hhmm>\d{3,4})(?P<ap>[AP]?)")
    hhmm = m["hhmm"].fillna("").str.zfill(4)
    ap = m["ap"].fillna("")

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


def clean_chicago_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardize Chicago data to the required unified schema."""
    out = pd.DataFrame(index=df.index)

    # Timestamp standardization.
    out["ts_start"] = pd.to_datetime(df.get("TRANSACTION_START"), errors="coerce")
    out["ts_end"] = pd.to_datetime(df.get("TRANSACTION_END"), errors="coerce")

    # Revenue and location mapping.
    out["revenue"] = pd.to_numeric(df.get("AMOUNT_PAID"), errors="coerce")
    meter = df.get("METER_ID", pd.Series([pd.NA] * len(df), index=df.index)).astype("string")
    out["location_id"] = "CHI_" + meter.fillna("UNKNOWN").str.strip().replace("", "UNKNOWN")

    # Required derived fields.
    out["duration_minutes"] = (out["ts_end"] - out["ts_start"]).dt.total_seconds() / 60.0
    if "city" not in df.columns:
        out["city"] = "California"
    else:
        out["city"] = df["city"].fillna("California")

    # Event IDs: deterministic and unique per row.
    transaction_id = df.get(
        "TRANSACTION_ID", pd.Series([pd.NA] * len(df), index=df.index)
    ).astype("string")
    out["event_id"] = "CHI_" + transaction_id.fillna("NA") + "_" + df.index.astype(str)

    # Keep rows unless timestamp order is explicitly invalid.
    out["revenue"] = out["revenue"].fillna(0)
    out["duration_minutes"] = out["duration_minutes"].fillna(60.0)
    out = out[(out["revenue"] >= 0) & (out["duration_minutes"] >= 0)].copy()
    invalid_time_order = (
        out["ts_start"].notna()
        & out["ts_end"].notna()
        & (out["ts_end"] < out["ts_start"])
    )
    out = out.loc[~invalid_time_order, UNIFIED_COLUMNS].copy()
    return out


def clean_nyc_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardize NYC data to the required unified schema."""
    out = pd.DataFrame(index=df.index)

    issue_date = _pick_first_existing(df, ["issue_date", "ISSUE_DATE"])
    violation_time = _pick_first_existing(df, ["violation_time", "VIOLATION_TIME"])
    parsed_time = _parse_nyc_violation_time(violation_time).fillna("00:00:00")
    issue_ts = pd.to_datetime(issue_date, errors="coerce")
    out["ts_start"] = pd.to_datetime(
        issue_ts.dt.strftime("%Y-%m-%d").fillna("") + " " + parsed_time, errors="coerce"
    )
    # Keep NYC rows even when issue_date/violation_time parsing is incomplete.
    out["ts_start"] = out["ts_start"].fillna(issue_ts)

    # NYC default duration = 60 minutes.
    out["duration_minutes"] = 60.0
    out["ts_end"] = out["ts_start"] + pd.to_timedelta(out["duration_minutes"], unit="m")

    fine = _pick_first_existing(df, ["fine_amount", "FINE_AMOUNT", "payment_amount"])
    out["revenue"] = pd.to_numeric(fine, errors="coerce")

    street = _pick_first_existing(df, ["street_name", "STREET_NAME", "violation_location"])
    out["location_id"] = "NYC_" + street.astype("string").fillna("UNKNOWN").str.strip().replace("", "UNKNOWN")
    out["city"] = "NYC"

    summons = _pick_first_existing(df, ["summons_number", "SUMMONS_NUMBER"]).astype("string")
    out["event_id"] = "NYC_" + summons.fillna("NA") + "_" + df.index.astype(str)

    # Relaxed rules: preserve NYC records by imputing non-critical missing values.
    out["revenue"] = out["revenue"].fillna(0)
    out["duration_minutes"] = out["duration_minutes"].fillna(60.0)
    out["ts_start"] = out["ts_start"].fillna(pd.Timestamp("1970-01-01 00:00:00"))
    out["ts_end"] = out["ts_end"].fillna(out["ts_start"] + pd.to_timedelta(60, unit="m"))
    out = out[(out["revenue"] >= 0) & (out["duration_minutes"] >= 0)].copy()
    invalid_time_order = (
        out["ts_start"].notna()
        & out["ts_end"].notna()
        & (out["ts_end"] < out["ts_start"])
    )
    out = out.loc[~invalid_time_order, UNIFIED_COLUMNS].copy()
    return out


def create_aggregations(unified_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create hourly and daily OLAP summaries by city."""
    temp = unified_df.copy()
    temp["hour"] = temp["ts_start"].dt.floor("h")
    temp["date"] = temp["ts_start"].dt.date

    summary_hourly = (
        temp.groupby(["city", "hour"], as_index=False)
        .agg(
            total_events=("event_id", "count"),
            total_revenue=("revenue", "sum"),
            avg_duration=("duration_minutes", "mean"),
        )
        .sort_values(["city", "hour"])
        .reset_index(drop=True)
    )

    summary_daily = (
        temp.groupby(["city", "date"], as_index=False)
        .agg(
            total_events=("event_id", "count"),
            total_revenue=("revenue", "sum"),
            avg_duration=("duration_minutes", "mean"),
        )
        .sort_values(["city", "date"])
        .reset_index(drop=True)
    )

    return summary_hourly, summary_daily


def main() -> None:
    # 1) Load data (paths unchanged).
    chicago_raw = pd.read_csv(CHICAGO_INPUT, low_memory=False)
    nyc_raw = pd.read_csv(NYC_INPUT, low_memory=False)

    # 2-9) Clean and merge.
    chicago_clean = clean_chicago_data(chicago_raw)
    nyc_clean = clean_nyc_data(nyc_raw)
    unified = pd.concat([chicago_clean, nyc_clean], ignore_index=True)[UNIFIED_COLUMNS]

    # 10) Aggregations.
    summary_hourly, summary_daily = create_aggregations(unified)

    # 11) Save outputs.
    unified.to_csv(CLEANED_OUTPUT, index=False)
    summary_hourly.to_csv(HOURLY_OUTPUT, index=False)
    summary_daily.to_csv(DAILY_OUTPUT, index=False)

    # 12) Validation prints.
    print("Saved files:")
    print(f"- {CLEANED_OUTPUT}")
    print(f"- {HOURLY_OUTPUT}")
    print(f"- {DAILY_OUTPUT}")

    print("\nValidation:")
    print(f"Unified shape: {unified.shape}")
    print("City counts:")
    print(unified["city"].value_counts(dropna=False).to_string())
    print("Unified null counts:")
    print(unified.isna().sum().to_string())
    print("\nUnified sample:")
    print(unified.head(10).to_string(index=False))

    print("\nHourly shape:", summary_hourly.shape)
    print("Daily shape:", summary_daily.shape)


if __name__ == "__main__":
    main()
