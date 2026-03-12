"""
Load IT_Incidents_v1.csv into Supabase incidents table.
Usage: python scripts/load_incidents.py
"""

import csv
import os
from datetime import datetime
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://gflmzyavputlzqbczctv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

CSV_PATH = os.path.join(os.path.dirname(__file__), "../Inputs/IT_Incidents_v1.csv")

STATE_MAP = {
    "Oh hold": "On hold",
}

def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y %H:%M").isoformat()
    except ValueError:
        return None

def clean_state(value: str):
    value = value.strip()
    return STATE_MAP.get(value, value)

def load():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "number":             row["Number"].strip(),
                "opened_at":          parse_date(row["OpenedAt"]),
                "opened_by":          row["OpenedBy"].strip() or None,
                "state":              clean_state(row["State"]),
                "contact_type":       row["Contact Type"].strip() or None,
                "assignment_group":   row["Assignment Group"].strip() or None,
                "assigned_to":        row["Assigned to"].strip() or None,
                "priority":           row["Priority"].strip() or None,
                "configuration_item": row["Configuration Item"].strip() or None,
                "resolution_tier":    row["Resolution Tier"].strip() or None,
                "short_description":  row["Short Description"].strip() or None,
                "caller":             row["Caller"].strip() or None,
                "label":              row["Label"].strip() or None,
                "resolution_notes":   row["Resolution Notes"].strip() or None,
            })

    print(f"Loaded {len(rows)} rows from CSV.")

    # Insert in batches of 100
    batch_size = 100
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        client.table("incidents").upsert(batch, on_conflict="number").execute()
        inserted += len(batch)
        print(f"  Inserted {inserted}/{len(rows)}...")

    print(f"Done. {inserted} incidents loaded into Supabase.")

if __name__ == "__main__":
    load()
