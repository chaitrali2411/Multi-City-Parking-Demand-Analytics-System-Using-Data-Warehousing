"""
VISUAL DASHBOARDS (matplotlib + seaborn + plotly)

Builds charts from cleaning/preprocessing CSV outputs (no DB required):
  - Time series of parking demand (hourly txn counts), faceted by city
  - Daily revenue by city (faceted, independent y-scales)
  - Heatmap of usage by hour × weekday (matplotlib + plotly)
  - Bar chart: utilization proxy (mean events per location)

Figures are written to outputs/figures/ (PNG @ 300 DPI + interactive HTML).
Companion insights: outputs/figures/INSIGHTS.md

Run from project root after cleaning/preprocessing:

  python src/visual_dashboards.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.io as pio
import seaborn as sns

from data_ingestion import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = PROJECT_ROOT / "outputs" / "figures"
MIN_VALID_PLOT_DATE = pd.Timestamp("2000-01-01")
FIG_DPI = 300


def _apply_matplotlib_style() -> None:
    """Consistent presentation style for matplotlib + seaborn."""
    sns.set_theme(style="whitegrid", context="notebook", font_scale=1.05, palette="deep")
    mpl.rcParams.update(
        {
            "savefig.dpi": FIG_DPI,
            "figure.dpi": 120,
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.titlesize": 14,
        }
    )


def _require_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run python src/cleaning_preprocessing.py first.")
    return pd.read_csv(path)


def _prepare_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    hourly = hourly.copy()
    if "date" in hourly.columns and "hour" in hourly.columns:
        hourly["period_start"] = pd.to_datetime(hourly["date"], errors="coerce") + pd.to_timedelta(
            hourly["hour"], unit="h"
        )
    else:
        hourly["period_start"] = pd.to_datetime(hourly["hour"], errors="coerce")
    hourly = hourly.dropna(subset=["period_start"])
    hourly = hourly[hourly["period_start"] >= MIN_VALID_PLOT_DATE].sort_values("period_start")
    if "txn_count" not in hourly.columns and "total_events" in hourly.columns:
        hourly["txn_count"] = hourly["total_events"]
    return hourly


def plot_demand_timeseries(hourly: pd.DataFrame) -> Path:
    """Facet by city so each city gets its own y-scale (avoids misleading shared scale)."""
    hourly = _prepare_hourly(hourly)
    if hourly.empty:
        raise ValueError("No hourly rows after date filter; cannot plot demand.")

    g = sns.relplot(
        data=hourly,
        x="period_start",
        y="txn_count",
        col="city",
        hue="city",
        kind="line",
        marker="o",
        linewidth=1.5,
        markersize=4,
        facet_kws={"sharey": False, "sharex": True},
        height=4,
        aspect=1.35,
        legend=False,
    )
    g.set_axis_labels("Time", "Transactions")
    g.set_titles("{col_name}")
    g.fig.suptitle("Parking Demand Analysis (Hourly Transactions)", y=1.02, fontweight="semibold")
    for ax in g.axes.flat:
        ax.grid(True, alpha=0.35)
    g.fig.autofmt_xdate()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "01_demand_timeseries_hourly.png"
    g.fig.tight_layout()
    g.fig.savefig(out, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(g.fig)
    return out


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.copy()
    daily["period_start"] = pd.to_datetime(daily["date"], errors="coerce")
    daily = daily.dropna(subset=["period_start"])
    daily = daily[daily["period_start"] >= MIN_VALID_PLOT_DATE].sort_values("period_start")
    if "revenue_sum" not in daily.columns and "total_revenue" in daily.columns:
        daily["revenue_sum"] = daily["total_revenue"]
    return daily


def plot_revenue_by_city_daily(daily: pd.DataFrame) -> Path:
    """Line plot faceted by city — independent y per facet; clearer than crowded grouped bars."""
    daily = _prepare_daily(daily)
    if daily.empty:
        raise ValueError("No daily rows after date filter; cannot plot revenue.")

    g = sns.relplot(
        data=daily,
        x="period_start",
        y="revenue_sum",
        col="city",
        hue="city",
        kind="line",
        marker="o",
        linewidth=1.8,
        markersize=5,
        facet_kws={"sharey": False, "sharex": True},
        height=4,
        aspect=1.35,
        legend=False,
    )
    g.set_axis_labels("Date", "Revenue (USD)")
    g.set_titles("{col_name}")
    g.fig.suptitle("Daily Parking Revenue Comparison", y=1.02, fontweight="semibold")
    for ax in g.axes.flat:
        ax.grid(True, alpha=0.35)
    g.fig.autofmt_xdate()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "02_revenue_daily_by_city.png"
    g.fig.tight_layout()
    g.fig.savefig(out, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(g.fig)
    return out


def plot_usage_heatmap(events: pd.DataFrame) -> tuple[Path, Path]:
    ev = events.copy()
    ev["ts_start"] = pd.to_datetime(ev["ts_start"], errors="coerce")
    ev = ev.dropna(subset=["ts_start"])
    ev = ev[ev["ts_start"] >= MIN_VALID_PLOT_DATE]
    ev["hour"] = ev["ts_start"].dt.hour
    ev["dow"] = ev["ts_start"].dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    heat = (
        ev.groupby(["city", "dow", "hour"], observed=False)
        .size()
        .reset_index(name="events")
    )
    heat["dow"] = pd.Categorical(heat["dow"], categories=order, ordered=True)
    heat = heat.sort_values(["city", "dow", "hour"])

    mpl_out = OUT_DIR / "03_usage_heatmap_matplotlib.png"
    cities = list(heat["city"].unique())
    n = len(cities)
    fig, axes = plt.subplots(1, n, figsize=(5.2 * n, 4.6), squeeze=False, sharey=True)
    for ax, city in zip(axes[0], cities):
        sub = heat[heat["city"] == city]
        pivot = sub.pivot(index="dow", columns="hour", values="events").reindex(order)
        pivot = pivot.reindex(columns=list(range(24)), fill_value=0)
        im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd", interpolation="nearest")
        ax.set_title(f"{city}", fontsize=12)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xticklabels(range(0, 24, 2))
        ax.set_xlabel("Hour of day")
        ax.set_ylabel("Weekday")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Events")
    fig.suptitle("Parking Usage Heatmap (Hour vs Weekday)", fontsize=14, fontweight="semibold", y=1.02)
    fig.tight_layout()
    fig.savefig(mpl_out, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig)

    fig_px = px.density_heatmap(
        heat,
        x="hour",
        y="dow",
        z="events",
        facet_col="city",
        category_orders={"dow": order},
        color_continuous_scale="YlOrRd",
        title="Parking Usage Heatmap (Hour vs Weekday)",
    )
    fig_px.update_layout(height=480, title_font_size=16)
    html_out = OUT_DIR / "03_usage_heatmap_interactive.html"
    pio.write_html(fig_px, file=str(html_out), include_plotlyjs="cdn", full_html=True)
    return mpl_out, html_out


def plot_utilization_bars(events: pd.DataFrame) -> Path:
    ev = events.copy()
    util = (
        ev.groupby(["city", "location_id"], observed=False)
        .agg(events=("event_id", "count"), revenue=("revenue", "sum"))
        .reset_index()
    )
    city_avg = util.groupby("city")["events"].mean().reset_index()
    city_avg.columns = ["city", "avg_events_per_location"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    sns.barplot(
        data=city_avg,
        x="city",
        y="avg_events_per_location",
        hue="city",
        palette="deep",
        legend=False,
        ax=ax,
    )
    ax.set_title("Parking Utilization Comparison by City", fontsize=13, fontweight="semibold")
    ax.set_xlabel("City")
    ax.set_ylabel("Avg events per location")
    ax.grid(True, axis="y", alpha=0.35)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "04_utilization_mean_events_per_location.png"
    fig.tight_layout()
    fig.savefig(out, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def write_figure_insights(out_path: Path) -> Path:
    """Short interpretation bullets for report / submission (next to figures)."""
    text = """# Figure insights

Brief notes for each dashboard output in this folder. Use alongside the PNG/HTML exports.

---

## `01_demand_timeseries_hourly.png` — Parking demand (hourly)

- **What it shows:** Transaction counts aggregated to each hour, split by city in separate panels so each city has its own vertical scale.
- **Why it matters:** Comparing cities on one shared y-axis can hide spikes in the smaller city; faceting makes both temporal patterns and relative intensity within each city readable.

---

## `02_revenue_daily_by_city.png` — Daily revenue

- **What it shows:** Daily total revenue over time, one line per panel (city), with independent y-scales per city.
- **Why it matters:** Revenue magnitudes often differ sharply by city; separate scales avoid compressing the smaller series into a flat line while still aligning dates on the x-axis.

---

## `03_usage_heatmap_matplotlib.png` / `03_usage_heatmap_interactive.html` — Hour × weekday

- **What it shows:** How event counts distribute across hour of day and weekday, with one heatmap per city (darker = more events).
- **Why it matters:** Surfaces peak windows for operations or policy (e.g. enforcement, pricing, staffing) and makes weekend vs weekday differences obvious at a glance.

---

## `04_utilization_mean_events_per_location.png` — Utilization proxy

- **What it shows:** Mean number of events per distinct `location_id` within each city (simple spread-of-demand proxy).
- **Why it matters:** Highlights whether activity is concentrated in fewer locations (higher mean per location) vs spread thinly across many sites, which supports infrastructure and planning narratives.

---

*Figures generated by `src/visual_dashboards.py` (matplotlib + seaborn + plotly; PNG saved at 300 DPI for print).*
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def main() -> None:
    _apply_matplotlib_style()

    hourly = _require_csv(DATA_DIR / "summary_hourly.csv")
    daily = _require_csv(DATA_DIR / "summary_daily.csv")
    events = _require_csv(DATA_DIR / "cleaned_unified_parking.csv")

    paths = [
        plot_demand_timeseries(hourly),
        plot_revenue_by_city_daily(daily),
        *plot_usage_heatmap(events),
        plot_utilization_bars(events),
        write_figure_insights(OUT_DIR / "INSIGHTS.md"),
    ]
    print("Figures written:")
    for p in paths:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
