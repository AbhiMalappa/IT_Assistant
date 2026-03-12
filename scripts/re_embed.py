"""
Embed all incidents from Supabase and upsert into Pinecone.
Run this when:
  - Loading data for the first time
  - Switching embedding providers (change EMBEDDING_PROVIDER in .env first)

Usage: python scripts/re_embed.py
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from db import incidents as db
from vectorstore.pinecone_store import PineconeStore

NAMESPACE = "incidents"


def build_embed_text(inc: dict) -> str:
    """Combine the most meaningful fields into a single string for embedding."""
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
    """Universal + incident-specific metadata stored alongside each vector."""
    return {
        # Universal fields — present for all source types
        "source_type": "incident",
        "source_id": str(inc["id"]),
        "title": inc.get("short_description") or inc.get("number", ""),
        "created_at": str(inc.get("opened_at", "")),

        # Incident-specific fields — used for filtered search
        "number": inc.get("number", ""),
        "priority": inc.get("priority") or "",
        "state": inc.get("state") or "",
        "assignment_group": inc.get("assignment_group") or "",
        "configuration_item": inc.get("configuration_item") or "",
        "label": inc.get("label") or "",
    }


def re_embed_all():
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

    all_incidents = db.get_all()
    total = len(all_incidents)
    print(f"Embedding {total} incidents using '{provider}' → namespace '{NAMESPACE}'...")

    for i, inc in enumerate(all_incidents, 1):
        text = build_embed_text(inc)
        vector = embedder.embed(text)
        metadata = build_metadata(inc)
        store.upsert(id=str(inc["id"]), vector=vector, metadata=metadata, namespace=NAMESPACE)
        print(f"  [{i}/{total}] {inc['number']} — {inc.get('short_description', '')[:60]}")

    print(f"\nDone. {total} incidents upserted into Pinecone namespace '{NAMESPACE}'.")


if __name__ == "__main__":
    re_embed_all()
