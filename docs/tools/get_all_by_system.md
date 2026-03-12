# Tool: get_all_by_system

## Purpose

Fetches all incidents associated with a specific system or configuration item from Supabase. Unlike `search_incidents` which returns the top-k most semantically similar results, this tool retrieves the complete set of incidents for a system — up to the configured limit.

Use this when the user wants full coverage for a system, not just the most relevant matches.

---

## When Claude Picks This Tool

Claude selects `get_all_by_system` when the user asks for all or every incident related to a system:
- "Give me all SAP incidents"
- "Every printer issue we've had"
- "Show me all network incidents"
- "Pull all incidents for the workstation team"
- "What are all the server incidents?"

The keyword signals are words like *all*, *every*, *complete list*, *full picture* paired with a system name. For questions like "top 5 printer issues" or "how many network incidents?", Claude uses `sql_query` instead.

---

## Inputs

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `system` | string | Yes | — | The system or configuration item name to search for (e.g., `SAP`, `Printer`, `Server`, `Workstation`) |
| `limit` | integer | No | 100 | Maximum number of records to return |

---

## How It Works

```
User asks for all incidents for a system
      ↓
get_all_by_system("SAP")
      ↓
Supabase: SELECT * FROM incidents
          WHERE configuration_item ILIKE '%SAP%'
          LIMIT 100
      ↓
Returns list of matching incident records
```

The search uses a **case-insensitive partial match** (`ILIKE '%system%'`) against the `configuration_item` column. This means:
- `"SAP"` matches `"SAP ERP"`, `"SAP Fiori"`, `"SAP BW"`, etc.
- `"Printer"` matches `"HP Printer"`, `"Network Printer"`, etc.
- The match is case-insensitive — `"sap"` and `"SAP"` return the same results.

---

## Output

A list of incident records (dicts), ordered by Supabase default (insertion order). Each record contains all columns from the incidents table:

```
id, number, opened_at, opened_by, state, contact_type, assignment_group,
assigned_to, priority, configuration_item, resolution_tier, short_description,
caller, label, resolution_notes, created_at, updated_at
```

---

## Constraints and Limits

- **Default limit: 100.** If there are more than 100 matching incidents, only the first 100 are returned. Claude may note this limitation in its response.
- **No date filter.** Unlike `sql_query`, this tool does not restrict results to the past 2 years. It returns all matching incidents regardless of when they were opened.
- **Partial match only.** The system name is matched against `configuration_item` only — not `short_description`, `label`, or `assignment_group`. If a system appears in descriptions but not in the configuration_item field, it will not be found.
- **No ranking.** Results are not sorted by relevance, recency, or priority. Use `sql_query` if you need ordered or ranked results.
- **No vector search.** This tool bypasses Pinecone entirely. It only queries Supabase.

---

## Example Calls

**All SAP incidents (default limit):**
```json
{
  "system": "SAP"
}
```

**All printer incidents, up to 50:**
```json
{
  "system": "Printer",
  "limit": 50
}
```

**All server incidents:**
```json
{
  "system": "Server"
}
```

---

## Difference from search_incidents

| | `search_incidents` | `get_all_by_system` |
|---|---|---|
| Method | Semantic vector similarity | Database ILIKE filter |
| Coverage | Top-k most relevant | All matching (up to limit) |
| Ranking | By similarity score | No ranking |
| Date filter | None | None |
| Best for | "How are SAP issues resolved?" | "Give me every SAP incident" |

---

## Data Source

- **Supabase** `incidents` table, queried directly via `supabase-py`

---

## Related Tools

| Tool | Use instead when... |
|---|---|
| `search_incidents` | User wants the most relevant incidents for a topic, not full coverage |
| `get_incident_by_number` | User mentions a specific INC number |
| `sql_query` | User wants counts, rankings, or filtered aggregations for a system |
