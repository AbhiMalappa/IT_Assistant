# Tool: get_incident_by_number

## Purpose

Exact lookup of a single IT incident by its INC number. Fetches the full incident record directly from Supabase. No embeddings or vector search involved — this is a simple primary-key-style database lookup.

Use this when the user references a specific incident number. It is the fastest and most precise way to retrieve a known incident.

---

## When Claude Picks This Tool

Claude selects `get_incident_by_number` whenever the user mentions a specific INC number in their message:
- "What is the status of INC17089320?"
- "Summarize INC17089043"
- "Who is assigned to INC17091234?"
- "Is INC17089320 resolved?"
- "Tell me everything about INC17089043"

Claude detects the INC pattern in the user's message and calls this tool first, before considering any other tool.

---

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `number` | string | Yes | The incident number, e.g. `INC17089320`. Case-insensitive — normalized to uppercase internally. |

---

## How It Works

```
User message (contains INC number)
      ↓
Claude extracts the INC number
      ↓
get_incident_by_number("INC17089320")
      ↓
Supabase: SELECT * FROM incidents WHERE number = 'INC17089320'
      ↓
Returns full incident record (or None if not found)
```

The number is uppercased before querying, so `inc17089320`, `INC17089320`, and `Inc17089320` all work.

---

## Output

A single incident record (dict) with all columns from the incidents table, or `None` if no incident with that number exists.

```
id, number, opened_at, opened_by, state, contact_type, assignment_group,
assigned_to, priority, configuration_item, resolution_tier, short_description,
caller, label, resolution_notes, created_at, updated_at
```

---

## Constraints and Limits

- **Exact match only:** The number must match exactly (after uppercasing). Partial matches or fuzzy matching are not supported. `INC1708` will not return `INC17089320`.
- **Single result:** Always returns one incident or nothing. Cannot return multiple incidents in one call.
- **No fallback search:** If the number doesn't exist in Supabase, the tool returns `None`. Claude will report that no incident was found — it will not attempt a semantic search as a fallback.
- **No vector search:** This tool bypasses Pinecone entirely. It only queries Supabase.

---

## Example Calls

**Standard lookup:**
```json
{
  "number": "INC17089320"
}
```

**Lowercase input (normalized automatically):**
```json
{
  "number": "inc17089320"
}
```

---

## What Claude Does with the Result

When the incident is found, Claude typically provides:
- A summary of the incident (description, priority, state)
- Who it is assigned to and which team
- Resolution notes if the incident is closed
- The INC number in the response (per response rules)

When the incident is not found, Claude states clearly that no incident with that number exists. It does not fabricate details.

---

## Data Source

- **Supabase** `incidents` table, queried directly via `supabase-py`

---

## Related Tools

| Tool | Use instead when... |
|---|---|
| `search_incidents` | User describes an issue but doesn't know a specific INC number |
| `get_all_by_system` | User wants all incidents for a system, not one specific record |
| `sql_query` | User wants counts or stats about multiple incidents |
