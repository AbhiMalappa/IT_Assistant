# Tool: search_incidents

## Purpose

Semantic similarity search over past IT incidents. Converts the user's question into an embedding vector, searches Pinecone for the closest matching incident vectors, then fetches the full incident records from Supabase.

Use this when the question is open-ended and descriptive — the user is looking for incidents that are *about* something, not a specific incident number or a count.

---

## When Claude Picks This Tool

Claude selects `search_incidents` for questions like:
- "Why does SAP keep failing?"
- "How are printer issues usually resolved?"
- "Find incidents related to network outages"
- "What causes login failures?"
- "Are there any past incidents similar to what we're seeing with the VPN?"

It is **not** suitable for:
- Counting or ranking (use `sql_query`)
- Looking up a specific INC number (use `get_incident_by_number`)
- Getting every incident for a system (use `get_all_by_system`)

---

## Inputs

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | Natural language description of the incident or issue to search for |
| `top_k` | integer | No | 5 | Number of results to return. Max 20. |
| `filters` | object | No | None | Pinecone metadata filters to narrow results |

### Filters

Filters are applied at the Pinecone vector search level, before fetching from Supabase. Supported filter keys:

| Key | Example |
|---|---|
| `priority` | `{"priority": {"$eq": "Critical"}}` |
| `state` | `{"state": {"$eq": "Open"}}` |
| `assignment_group` | `{"assignment_group": {"$eq": "Network Team"}}` |
| `configuration_item` | `{"configuration_item": {"$eq": "SAP"}}` |
| `label` | `{"label": {"$eq": "Hardware"}}` |

Filter syntax follows the [Pinecone filter spec](https://docs.pinecone.io/guides/data/filter-with-metadata).

---

## How It Works (Pipeline)

```
User query (text)
      ↓
OpenAI text-embedding-3-large
      ↓
3072-dimension vector
      ↓
Pinecone similarity search (namespace: "incidents")
      ↓
Top-k matching incident IDs (source_id in metadata)
      ↓
Supabase: fetch full incident records by ID
      ↓
Return list of incident dicts
```

---

## Output

A list of incident records (dicts), ordered by semantic similarity (most relevant first). Each record contains all columns from the incidents table:

```
id, number, opened_at, opened_by, state, contact_type, assignment_group,
assigned_to, priority, configuration_item, resolution_tier, short_description,
caller, label, resolution_notes, created_at, updated_at
```

---

## Constraints and Limits

- **Top-k cap:** Max 20 results per call. Requesting more than 20 is ignored by the tool definition.
- **Coverage:** Only returns the closest `top_k` matches — not all incidents. If you need full coverage for a system, use `get_all_by_system` instead.
- **No date filter:** Unlike `sql_query`, this tool does not automatically restrict to the past 2 years. Historical incidents may appear in results if they are semantically relevant.
- **Embedding model dependency:** Results are only as good as the embedding model. Incidents with sparse or vague descriptions may not surface well.
- **Namespace:** Always searches the `"incidents"` namespace in Pinecone. Changes, documents, and transcripts (future sources) live in separate namespaces and are not searched here.

---

## Example Calls

**Basic search:**
```json
{
  "query": "SAP system unavailable during payroll run",
  "top_k": 5
}
```

**Filtered search — only Critical priority:**
```json
{
  "query": "network connectivity issues",
  "top_k": 10,
  "filters": {"priority": {"$eq": "Critical"}}
}
```

**Filtered search — only Open incidents for a specific team:**
```json
{
  "query": "printer not responding",
  "top_k": 5,
  "filters": {
    "state": {"$eq": "Open"},
    "assignment_group": {"$eq": "Desktop Support"}
  }
}
```

---

## Data Source

- **Vector index:** Pinecone, index `it-assistant`, namespace `incidents`
- **Full records:** Supabase `incidents` table
- **Embedding model:** OpenAI `text-embedding-3-large` (3072 dimensions), switchable to Voyage AI via `EMBEDDING_PROVIDER` env var

---

## Related Tools

| Tool | Use instead when... |
|---|---|
| `get_incident_by_number` | User mentions a specific INC number |
| `get_all_by_system` | User wants every incident for a system, not just top matches |
| `sql_query` | User wants counts, rankings, or trend analysis |
