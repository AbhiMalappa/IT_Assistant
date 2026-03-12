# Tool: sql_query

## Purpose

Executes a SELECT SQL query against the incidents database. Designed for aggregation, counting, ranking, and trend analysis — questions that require looking across all incidents, not just the top-k most similar ones.

This tool gives Claude the ability to answer data analysis questions that vector search fundamentally cannot handle.

---

## When Claude Picks This Tool

Claude selects `sql_query` for analytical questions:
- "How many open incidents are there?"
- "Top 5 printer issues by count"
- "Which assignment group has the most critical incidents?"
- "How many incidents were opened last month?"
- "What is the breakdown of incidents by priority?"
- "Which configuration item has the most unresolved incidents?"
- "Show me incident trends by label"

The trigger is any question involving counts, rankings, groupings, averages, or comparisons across multiple incidents.

---

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | Yes | A SELECT SQL query against the `incidents` table |

### incidents Table — Available Columns

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `number` | text | INC number, e.g. `INC17089320` |
| `opened_at` | timestamptz | When the incident was opened |
| `opened_by` | text | Who opened it |
| `state` | text | `Open`, `Closed`, `In Progress`, `Cancelled`, `On hold` |
| `contact_type` | text | How it was reported |
| `assignment_group` | text | Team responsible |
| `assigned_to` | text | Individual responsible |
| `priority` | text | `Low`, `Medium`, `High`, `Critical` |
| `configuration_item` | text | System or asset involved |
| `resolution_tier` | text | Support tier that resolved it |
| `short_description` | text | One-line summary |
| `caller` | text | Who reported the issue |
| `label` | text | Category label |
| `resolution_notes` | text | How it was resolved |
| `created_at` | timestamptz | Row creation time |
| `updated_at` | timestamptz | Row last update time |

---

## Safety Guards

Every query passes through six layers of validation before execution. These prevent runaway queries, data exposure, and performance issues.

### Guard 1 — SELECT Only

```
Only SELECT queries are permitted.
```

Any query that does not start with `SELECT` is rejected immediately with:
```
ValueError: Only SELECT queries are permitted.
```

This blocks INSERT, UPDATE, DELETE, DROP, TRUNCATE, and any DDL or DML statement.

---

### Guard 2 — Table Whitelist

```
Allowed tables: incidents
```

The query is parsed for all `FROM` and `JOIN` references using a regex. Any table not in the whitelist is rejected:
```
ValueError: Query references disallowed table(s): {'users'}. Allowed: {'incidents'}
```

Currently only `incidents` is whitelisted. When the `changes` table is added in the future, it will be added to the whitelist at that time.

This prevents:
- Accidentally querying internal Supabase system tables
- Querying tables that don't exist in the schema
- Data exfiltration from unintended tables

---

### Guard 3 — 1-Year Date Filter Auto-Injection

```
All queries are automatically scoped to incidents opened in the past 2 years.
Filter: opened_at >= NOW() - INTERVAL '2 years'
```

**Behavior:**
- If the query already contains `opened_at` anywhere in it, the filter is left as-is (assumed the query already handles date scoping).
- If the query has no `opened_at` reference, the filter is automatically injected:
  - If a `WHERE` clause exists → the filter is prepended: `WHERE opened_at >= NOW() - INTERVAL '2 years' AND ...`
  - If no `WHERE` clause → one is inserted before `GROUP BY`, `ORDER BY`, `HAVING`, or `LIMIT` (whichever comes first)
  - If none of those keywords exist → appended to the end of the query

**Before and after examples:**

```sql
-- Query as written by Claude
SELECT state, COUNT(*) FROM incidents GROUP BY state ORDER BY 2 DESC LIMIT 10;

-- Query after auto-injection
SELECT state, COUNT(*) FROM incidents WHERE opened_at >= NOW() - INTERVAL '2 years' GROUP BY state ORDER BY 2 DESC LIMIT 10;
```

```sql
-- Query already has opened_at — left unchanged
SELECT COUNT(*) FROM incidents WHERE opened_at >= NOW() - INTERVAL '6 months';
```

This guard ensures results stay relevant and prevents accidentally counting all historical incidents from the beginning of time.

---

### Guard 4 — Auto-LIMIT 200

If the query does not contain a `LIMIT` clause, one is automatically appended:
```sql
LIMIT 200
```

This caps result set size and prevents unbounded data from being returned to Claude's context.

---

### Guard 5 — Statement Timeout (30 seconds)

```sql
SET statement_timeout = '30s'
```

This is executed on the database connection before every query. If the query takes longer than 30 seconds, Postgres automatically cancels it with:
```
ERROR: canceling statement due to statement timeout
```

This protects against:
- Accidentally expensive queries (missing indexes, large scans)
- Queries that stall due to lock contention
- Any query that is unexpectedly slow

---

### Guard 6 — Row Estimate Guard (EXPLAIN)

Before executing the actual query, the tool runs:
```sql
EXPLAIN <query>
```

It parses the first `rows=N` estimate from the output. If the estimated row count exceeds **10,000**, the query is rejected before it runs:
```
ValueError: Query would scan ~45,230 estimated rows (limit: 10,000). Add more specific filters.
```

**Why this matters:**
- EXPLAIN is fast (no data is read) — it uses Postgres's planner statistics
- The row limit is intentionally conservative to prevent any single query from overloading the database
- This fires before the actual query, so a runaway query never reaches the database

**Note:** This is an *estimate*, not an exact count. Postgres planner estimates can be off, especially on tables with stale statistics. The guard is intentionally conservative.

---

## Execution Order

All six guards run in this order on every query:

```
1. SELECT-only check
2. Table whitelist validation
3. 1-year date filter injection
4. Auto-LIMIT 200 (if missing)
5. Statement timeout set (30s)
6. Row estimate guard (EXPLAIN) ← rejects before execution if too wide
7. Query execution
```

---

## Output

A list of dicts representing the query result rows. Column names match the SELECT clause.

**Example — incident count by state:**
```json
[
  {"state": "Closed", "count": 312},
  {"state": "Open", "count": 87},
  {"state": "In Progress", "count": 63},
  {"state": "On hold", "count": 31},
  {"state": "Cancelled", "count": 17}
]
```

---

## Example Queries Claude Generates

**Count by state:**
```sql
SELECT state, COUNT(*) as count
FROM incidents
WHERE opened_at >= NOW() - INTERVAL '2 years'
GROUP BY state
ORDER BY count DESC
LIMIT 10;
```

**Top assignment groups by critical incident count:**
```sql
SELECT assignment_group, COUNT(*) as critical_count
FROM incidents
WHERE priority = 'Critical'
  AND opened_at >= NOW() - INTERVAL '2 years'
GROUP BY assignment_group
ORDER BY critical_count DESC
LIMIT 10;
```

**Top configuration items by open incident count:**
```sql
SELECT configuration_item, COUNT(*) as open_count
FROM incidents
WHERE state = 'Open'
  AND opened_at >= NOW() - INTERVAL '2 years'
GROUP BY configuration_item
ORDER BY open_count DESC
LIMIT 10;
```

---

## Constraints Summary

| Constraint | Value | Behavior on violation |
|---|---|---|
| Query type | SELECT only | Rejected immediately |
| Allowed tables | `incidents` | Rejected immediately |
| Date scope | Past 2 years | Auto-injected if missing |
| Result size | 200 rows max | Auto-appended if missing |
| Statement timeout | 30 seconds | Postgres cancels the query |
| Row estimate | 10,000 rows max | Rejected before execution |

---

## Future Extensions

When the `changes` table is added to the schema:
- `changes` will be added to `ALLOWED_TABLES` in `bot/tools.py`
- Claude will be able to query change records alongside incidents
- Cross-table queries (e.g., incidents joined to changes) will become possible

---

## Data Source

- **Supabase** (Postgres), queried directly via `psycopg2` using `DATABASE_URL`
- Uses `RealDictCursor` so column names are preserved in results

---

## Related Tools

| Tool | Use instead when... |
|---|---|
| `search_incidents` | User asks open-ended questions about past incidents |
| `get_incident_by_number` | User mentions a specific INC number |
| `get_all_by_system` | User wants every incident for a system without aggregation |
