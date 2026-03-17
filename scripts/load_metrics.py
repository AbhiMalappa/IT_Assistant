"""
Load store_order_count.csv and api_traffic.csv into Supabase time_series_metrics table.
Usage: python scripts/load_metrics.py
"""

import csv
import os
from datetime import datetime, timezone
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://gflmzyavputlzqbczctv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

CSV_FILES = [
    os.path.join(os.path.dirname(__file__), "../Inputs/store_order_count.csv"),
    os.path.join(os.path.dirname(__file__), "../Inputs/api_traffic.csv"),
]


def parse_timestamp(value: str):
    value = value.strip().strip('"')
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").isoformat()


def load_csv(path: str) -> list:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "metric":    row["metric"].strip().strip('"'),
                "timestamp": parse_timestamp(row["_time"]),
                "value":     float(row["count_value"]),
            })
    return rows


def load():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    all_rows = []
    for path in CSV_FILES:
        rows = load_csv(path)
        print(f"  {os.path.basename(path)}: {len(rows)} rows")
        all_rows.extend(rows)

    print(f"Total: {len(all_rows)} rows. Inserting...")

    batch_size = 500
    inserted = 0
    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i:i + batch_size]
        client.table("time_series_metrics").upsert(batch, on_conflict="metric,timestamp").execute()
        inserted += len(batch)
        print(f"  {inserted}/{len(all_rows)}...")

    print(f"Done. {inserted} rows loaded into time_series_metrics.")


if __name__ == "__main__":
    load()
