"""
Delta sync: IT_Incidents_v1.csv → Supabase + Pinecone.

Detects new, modified, and deleted records and applies only the necessary changes.
- New records     → INSERT to Supabase, embed + upsert to Pinecone
- Modified records → UPDATE in Supabase, re-embed + upsert to Pinecone
- Deleted records  → DELETE from Supabase, delete vector from Pinecone
- Unchanged       → skipped entirely (no API calls)

Usage: python scripts/sync_incidents.py
"""

import csv
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
from db.supabase_client import supabase
from vectorstore.pinecone_store import PineconeStore

CSV_PATH = os.path.join(os.path.dirname(__file__), "../Inputs/IT_Incidents_v1.csv")
NAMESPACE = "incidents"
EMBED_BATCH_SIZE = 50

STATE_MAP = {"Oh hold": "On hold"}


# ---------------------------------------------------------------------------
# Helpers shared with load_incidents.py
# ---------------------------------------------------------------------------

def parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y %H:%M").isoformat()
    except ValueError:
        return None


def clean_state(value: str) -> str:
    value = value.strip()
    return STATE_MAP.get(value, value)


def row_to_record(row: dict) -> dict:
    """Normalise a CSV row into the same shape used by load_incidents.py."""
    return {
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
    }


def normalise_date(value) -> str:
    """Strip timezone info so CSV-parsed and Supabase-returned dates hash the same."""
    if not value:
        return ""
    return str(value)[:19]  # keep 'YYYY-MM-DDTHH:MM:SS', drop '+00:00' or any tz suffix


def record_hash(record: dict) -> str:
    """MD5 hash of the record's CSV-sourced fields — used to detect changes."""
    fields = {
        "opened_at":          normalise_date(record.get("opened_at")),
        "opened_by":          record.get("opened_by"),
        "state":              record.get("state"),
        "contact_type":       record.get("contact_type"),
        "assignment_group":   record.get("assignment_group"),
        "assigned_to":        record.get("assigned_to"),
        "priority":           record.get("priority"),
        "configuration_item": record.get("configuration_item"),
        "resolution_tier":    record.get("resolution_tier"),
        "short_description":  record.get("short_description"),
        "caller":             record.get("caller"),
        "label":              record.get("label"),
        "resolution_notes":   record.get("resolution_notes"),
    }
    serialised = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.md5(serialised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Embedding helpers (mirrors re_embed.py)
# ---------------------------------------------------------------------------

def build_embed_text(inc: dict) -> str:
    parts = [
        inc.get("number", ""),
        inc.get("short_description", ""),
        inc.get("label", ""),
        inc.get("configuration_item", ""),
        inc.get("assignment_group", ""),
        inc.get("resolution_notes", ""),
    ]
    return " ".join(p for p in parts if p)


def build_metadata(inc: dict) -> dict:
    return {
        "source_type":        "incident",
        "source_id":          str(inc["id"]),
        "title":              inc.get("short_description") or inc.get("number", ""),
        "created_at":         str(inc.get("opened_at", "")),
        "number":             inc.get("number", ""),
        "priority":           inc.get("priority") or "",
        "state":              inc.get("state") or "",
        "assignment_group":   inc.get("assignment_group") or "",
        "configuration_item": inc.get("configuration_item") or "",
        "label":              inc.get("label") or "",
    }


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def fetch_all_db() -> dict:
    """Return all DB incidents keyed by number. Also carries id (UUID)."""
    response = supabase.table("incidents").select("*").execute()
    return {r["number"]: r for r in response.data}


def fetch_by_numbers(numbers: list) -> list:
    """Fetch fresh DB rows for a list of INC numbers (after upsert, to get UUIDs)."""
    response = supabase.table("incidents").select("*").in_("number", numbers).execute()
    return response.data


def upsert_batch(records: list) -> None:
    for i in range(0, len(records), 100):
        supabase.table("incidents").upsert(
            records[i:i + 100], on_conflict="number"
        ).execute()


def delete_by_numbers(numbers: list) -> None:
    for number in numbers:
        supabase.table("incidents").delete().eq("number", number).execute()


# ---------------------------------------------------------------------------
# Pinecone helpers
# ---------------------------------------------------------------------------

def upsert_to_pinecone(incidents: list, embedder, store: PineconeStore) -> None:
    """Embed and upsert a list of incidents to Pinecone in batches."""
    texts = [build_embed_text(inc) for inc in incidents]
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch_texts = texts[i:i + EMBED_BATCH_SIZE]
        batch_incs = incidents[i:i + EMBED_BATCH_SIZE]
        vectors = embedder.embed_batch(batch_texts)
        for inc, vector in zip(batch_incs, vectors):
            store.upsert(
                id=str(inc["id"]),
                vector=vector,
                metadata=build_metadata(inc),
                namespace=NAMESPACE,
            )
        print(f"    Pinecone upsert: {min(i + EMBED_BATCH_SIZE, len(texts))}/{len(texts)}")


def delete_from_pinecone(uuids: list, store: PineconeStore) -> None:
    for uuid in uuids:
        store.delete(id=uuid, namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# Main sync
# ---------------------------------------------------------------------------

def sync():
    print("=" * 60)
    print("  IT Incidents — Delta Sync")
    print("=" * 60)

    # --- Load CSV -----------------------------------------------------------
    csv_records = {}
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = row_to_record(row)
            csv_records[rec["number"]] = rec

    print(f"\nCSV records:      {len(csv_records)}")

    # --- Load DB ------------------------------------------------------------
    db_records = fetch_all_db()
    print(f"Supabase records: {len(db_records)}")

    # --- Diff ---------------------------------------------------------------
    csv_numbers = set(csv_records.keys())
    db_numbers  = set(db_records.keys())

    new_numbers     = csv_numbers - db_numbers
    deleted_numbers = db_numbers - csv_numbers
    common_numbers  = csv_numbers & db_numbers

    modified_numbers = set()
    unchanged_numbers = set()
    for num in common_numbers:
        csv_hash = record_hash(csv_records[num])
        db_hash  = record_hash(db_records[num])
        if csv_hash != db_hash:
            modified_numbers.add(num)
        else:
            unchanged_numbers.add(num)

    print(f"\n--- Diff Summary ---")
    print(f"  New:       {len(new_numbers)}")
    print(f"  Modified:  {len(modified_numbers)}")
    print(f"  Deleted:   {len(deleted_numbers)}")
    print(f"  Unchanged: {len(unchanged_numbers)}")

    if not new_numbers and not modified_numbers and not deleted_numbers:
        print("\nNo changes detected. Supabase and Pinecone are already in sync.")
        return

    # --- Initialise embedder and Pinecone -----------------------------------
    provider = os.getenv("EMBEDDING_PROVIDER", "openai")
    if provider == "openai":
        from embeddings.openai_embedder import OpenAIEmbedder
        embedder = OpenAIEmbedder()
    else:
        from embeddings.voyage_embedder import VoyageEmbedder
        embedder = VoyageEmbedder()

    store = PineconeStore(
        api_key=os.environ["PINECONE_API_KEY"],
        index_name=os.environ["PINECONE_INDEX_NAME"],
    )

    # --- Handle deletions first (capture UUIDs before removing from DB) -----
    if deleted_numbers:
        print(f"\n[1/4] Deleting {len(deleted_numbers)} removed records...")
        deleted_uuids = [db_records[n]["id"] for n in deleted_numbers]

        print(f"  Deleting from Pinecone...")
        delete_from_pinecone(deleted_uuids, store)

        print(f"  Deleting from Supabase...")
        delete_by_numbers(list(deleted_numbers))
        print(f"  Done. Deleted: {sorted(deleted_numbers)}")
    else:
        print(f"\n[1/4] No deletions.")

    # --- Upsert new + modified to Supabase ----------------------------------
    to_upsert = [csv_records[n] for n in new_numbers | modified_numbers]
    if to_upsert:
        print(f"\n[2/4] Upserting {len(to_upsert)} records to Supabase "
              f"({len(new_numbers)} new, {len(modified_numbers)} modified)...")
        upsert_batch(to_upsert)
        print(f"  Done.")
    else:
        print(f"\n[2/4] No Supabase upserts needed.")

    # --- Fetch fresh DB rows to get UUIDs for new records -------------------
    if to_upsert:
        print(f"\n[3/4] Embedding and upserting to Pinecone...")
        updated_numbers = list(new_numbers | modified_numbers)
        fresh_rows = fetch_by_numbers(updated_numbers)
        upsert_to_pinecone(fresh_rows, embedder, store)
        print(f"  Done. {len(fresh_rows)} vectors upserted.")
    else:
        print(f"\n[3/4] No Pinecone upserts needed.")

    # --- Verification -------------------------------------------------------
    print(f"\n[4/4] Verification...")
    final_db = fetch_all_db()
    print(f"  CSV records:          {len(csv_records)}")
    print(f"  Supabase records:     {len(final_db)}")
    match = "✓ Match" if len(csv_records) == len(final_db) else "✗ Mismatch — investigate"
    print(f"  Status:               {match}")

    print(f"\n{'=' * 60}")
    print(f"  Sync complete.")
    print(f"  New: {len(new_numbers)} | Modified: {len(modified_numbers)} | Deleted: {len(deleted_numbers)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    sync()
