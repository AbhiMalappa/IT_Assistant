"""
Test script: forecast monthly incident counts for the next 3 months.

Data source priority:
  1. Supabase (if .env is present and SUPABASE_URL is set)
  2. CSV fallback (Inputs/IT_Incidents_v1.csv) — works without any credentials

Steps:
  1. Load incident data (Supabase or CSV)
  2. Aggregate counts by calendar month, exclude current partial month
  3. Run ExponentialSmoothingForecaster
  4. Print accuracy metrics, model comparison, and forecast
"""

import csv
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# Make sure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from forecasting.forecaster import ExponentialSmoothingForecaster


# ---------------------------------------------------------------------------
# Step 1: Load monthly incident counts
# ---------------------------------------------------------------------------

def _from_supabase() -> pd.Series:
    """Fetch opened_at timestamps from Supabase and aggregate by month."""
    from db.supabase_client import supabase
    response = supabase.table("incidents").select("opened_at").execute()
    rows = response.data
    if not rows:
        raise RuntimeError("No incidents found in Supabase.")

    current_month = datetime.now().strftime("%Y-%m")
    counts: dict = {}
    for row in rows:
        raw = row.get("opened_at")
        if not raw:
            continue
        month = raw[:7]   # 'YYYY-MM' from ISO timestamptz
        if month == current_month:
            continue      # exclude partial current month
        counts[month] = counts.get(month, 0) + 1
    return counts


def _from_csv() -> dict:
    """Read IT_Incidents_v1.csv and aggregate incident counts by month."""
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Inputs", "IT_Incidents_v1.csv"
    )
    current_month = datetime.now().strftime("%Y-%m")
    counts: dict = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = row.get("OpenedAt", "").strip()
            if not raw:
                continue
            try:
                dt = datetime.strptime(raw, "%m/%d/%Y %H:%M")
                month = dt.strftime("%Y-%m")
                if month == current_month:
                    continue
                counts[month] = counts.get(month, 0) + 1
            except ValueError:
                continue
    return counts


def fetch_monthly_counts() -> pd.Series:
    """
    Return a pd.Series of monthly incident counts, indexed by 'YYYY-MM', sorted ascending.
    Tries Supabase first; falls back to CSV if env vars are missing.
    Excludes the current (partial) month from all sources.
    """
    counts: dict = {}
    source = "unknown"

    if os.environ.get("SUPABASE_URL"):
        try:
            counts = _from_supabase()
            source = "Supabase"
        except Exception as e:
            print(f"[warn] Supabase fetch failed ({e}), falling back to CSV.")
            counts = _from_csv()
            source = "CSV"
    else:
        counts = _from_csv()
        source = "CSV"

    if not counts:
        raise RuntimeError("No complete months found in data source.")

    print(f"[info] Data source: {source}")
    series = pd.Series(counts, name="incident_count")
    series.index.name = "month"
    return series.sort_index()


# ---------------------------------------------------------------------------
# Step 2: Run forecaster
# ---------------------------------------------------------------------------

def run_forecast(series: pd.Series, periods: int = 3) -> None:
    print("\n" + "=" * 60)
    print("  IT Incident Volume Forecasting")
    print("=" * 60)

    print("\n--- Historical Data (input series) ---")
    for month, count in series.items():
        print(f"  {month}  →  {int(count):>4} incidents")

    print(f"\nTotal months: {len(series)} | Total incidents: {int(series.sum())}")

    # Fit
    forecaster = ExponentialSmoothingForecaster(
        seasonal_periods=12,    # monthly data, yearly cycle
        n_test=3,               # hold out last 3 months for evaluation
    )
    forecaster.fit(series)

    # Forecast
    result = forecaster.forecast(periods=periods)

    # ---------------------------------------------------------------------------
    # Print results
    # ---------------------------------------------------------------------------

    print("\n--- Model Comparison (ranked by MSE, lowest = best) ---")
    print(f"  {'Rank':<6} {'MSE':>10} {'R²':>8}  Model")
    print(f"  {'-'*6} {'-'*10} {'-'*8}  {'-'*40}")
    for m in result.all_models_ranked:
        marker = " ◄ BEST" if m["rank"] == 1 else ""
        print(f"  {m['rank']:<6} {m['mse']:>10.4f} {m['r2']:>8.4f}  {m['label']}{marker}")

    print(f"\n--- Best Model ---")
    print(f"  {result.best_model_label}")
    print(f"  Parameters: {result.best_model_params}")
    print(f"  Test MSE:   {result.mse}")
    print(f"  Test R²:    {result.r2}")

    print(f"\n--- Forecast: Next {result.forecast_periods} Months ---")
    for period, value in result.forecast:
        print(f"  {period}  →  {value:.1f} incidents (forecasted)")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    series = fetch_monthly_counts()
    run_forecast(series, periods=3)
