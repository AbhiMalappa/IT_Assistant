import os
import re
from typing import Dict, List, Optional

from vectorstore.pinecone_store import PineconeStore
from db import incidents as db
from bot.claude_client import respond

INC_PATTERN = re.compile(r'\bINC[\w-]+\b', re.IGNORECASE)


# Initialise embedding provider based on env var
_provider = os.getenv("EMBEDDING_PROVIDER", "openai")
if _provider == "openai":
    from embeddings.openai_embedder import OpenAIEmbedder
    embedder = OpenAIEmbedder()
else:
    from embeddings.voyage_embedder import VoyageEmbedder
    embedder = VoyageEmbedder()

# Initialise Pinecone
vector_store = PineconeStore(
    api_key=os.environ["PINECONE_API_KEY"],
    index_name=os.environ["PINECONE_INDEX_NAME"],
)


def run(user_message: str, filters: Optional[Dict] = None, top_k: int = 5, namespace: str = "incidents") -> str:
    # Check if the message references a specific INC number
    inc_match = INC_PATTERN.search(user_message)
    if inc_match:
        inc_number = inc_match.group(0).upper()
        incident = db.get_by_number(inc_number)
        if incident:
            return respond(user_message, [incident])

    # Step 1: Embed the user's query
    query_vector = embedder.embed(user_message)

    # Step 2: Search Pinecone for similar incidents within the given namespace
    matches = vector_store.search(query_vector, top_k=top_k, filters=filters, namespace=namespace)

    # Step 3: Fetch full incident details from Supabase using source_id
    incident_ids = [m.metadata["source_id"] for m in matches]
    incidents = db.get_by_ids(incident_ids)

    # Step 4: Build prompt and call Claude
    return respond(user_message, incidents)
