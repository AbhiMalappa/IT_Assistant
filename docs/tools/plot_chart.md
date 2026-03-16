# Tool: plot_chart

## Purpose

Generates a PNG chart from tabular data returned by a previous tool call and uploads it inline to Slack. Claude calls this tool after `sql_query` or `forecast_incidents` when a visual representation would help the user understand the data.

---

## When Claude Picks This Tool

Claude calls `plot_chart` as a **follow-up** to another tool when:

| Previous tool | Condition | Chart type |
|---|---|---|
| `sql_query` | Multiple rows with a categorical column + numeric column | `bar` or `horizontal_bar` |
| `sql_query` | Multiple rows with a date/period column + numeric column | `line` |
| `forecast_incidents` | Always | `forecast` |

Claude does **not** call `plot_chart` for:
- `search_incidents` — unstructured text results
- `get_incident_by_number` — single record detail
- `get_all_by_system` — raw record list, no aggregation
- Single-row SQL results

---

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `data` | array of objects | Yes | Row dicts from a previous tool result |
| `chart_type` | string (enum) | Yes | `"bar"`, `"line"`, `"horizontal_bar"`, or `"forecast"` |
| `x_column` | string | Yes | Column name for the x-axis |
| `y_column` | string | Yes | Column name for the y-axis (must be numeric) |
| `title` | string | Yes | Chart title, e.g. `"Incidents by Priority"` |
| `x_label` | string | No | Human-readable x-axis label. Defaults to `x_column` |
| `y_label` | string | No | Human-readable y-axis label. Defaults to `y_column` |
| `forecast_data` | array of objects | No | For `"forecast"` type only. List of `{period, forecasted_count}` from `forecast_incidents` |

### Chart type guide

| Type | Use when |
|---|---|
| `bar` | Categorical breakdown: incidents by state, priority, assignment group |
| `horizontal_bar` | Ranked list: top N systems by count — long category names fit better horizontally |
| `line` | Time series: incident count by month or week |
| `forecast` | Historical bars + forecast line; always use after `forecast_incidents` |

---

## How It Works

```
Claude calls plot_chart(data, chart_type, ...)
        ↓
chart_png/tool.py — calls generator + store
        ↓
chart_png/generator.py — builds Plotly Figure (no project knowledge)
        ↓
chart_png/store.py — saves both:
    /tmp/charts/{uuid}.png   ← for Slack inline upload
    /tmp/charts/{uuid}.html  ← for interactive URL
        ↓
Returns {"chart_path": "...", "chart_id": "uuid", "chart_title": "..."}
        ↓
agent.py — captures chart_path + chart_id from result
        ↓
agent.run() returns (text_response, chart_path, chart_id)
        ↓
slack_handler.py:
    1. Uploads PNG inline via files_upload_v2 → PNG appears in chat
    2. Posts "Open interactive chart" URL (if APP_URL is set)
    3. Deletes PNG immediately from /tmp
    4. Deletes HTML after 10 minutes from /tmp
```

---

## Output

Returns a dict:
```json
{
  "chart_path": "/tmp/charts/3f8a1b2c-....png",
  "chart_id": "3f8a1b2c-....",
  "chart_title": "Monthly Incident Volume"
}
```

If generation fails, returns:
```json
{
  "error": "Chart generation failed: <reason>"
}
```

---

## Example Calls

**Bar chart — incidents by priority:**
```json
{
  "data": [
    {"priority": "Critical", "count": 45},
    {"priority": "High", "count": 120},
    {"priority": "Medium", "count": 210},
    {"priority": "Low", "count": 135}
  ],
  "chart_type": "bar",
  "x_column": "priority",
  "y_column": "count",
  "title": "Incidents by Priority",
  "y_label": "Incident Count"
}
```

**Horizontal bar — top assignment groups:**
```json
{
  "data": [
    {"assignment_group": "SAP Support", "count": 98},
    {"assignment_group": "Network Team", "count": 74},
    {"assignment_group": "Desktop Support", "count": 61}
  ],
  "chart_type": "horizontal_bar",
  "x_column": "assignment_group",
  "y_column": "count",
  "title": "Top Assignment Groups by Volume"
}
```

**Forecast chart:**
```json
{
  "data": [
    {"period": "2025-01", "count": 42},
    {"period": "2025-02", "count": 38}
  ],
  "chart_type": "forecast",
  "x_column": "period",
  "y_column": "count",
  "title": "Monthly Incident Forecast",
  "forecast_data": [
    {"period": "2025-03", "forecasted_count": 41.5},
    {"period": "2025-04", "forecasted_count": 39.2},
    {"period": "2025-05", "forecasted_count": 40.1}
  ]
}
```

---

## Module Structure

```
chart_png/                  ← standalone internal package, no project knowledge
├── __init__.py
├── generator.py            ← builds Plotly Figure from data + config
├── store.py                ← saves Figure as both PNG and HTML to /tmp/charts/
└── tool.py                 ← thin wrapper: calls generator + store, returns chart_path + chart_id
```

`generator.py` and `store.py` know nothing about incidents or Slack — they accept generic data and return a figure or file paths. This makes the `chart_png` module reusable in other projects.

---

## Storage and Cleanup

Charts are saved to `/tmp/charts/` which is **ephemeral** — wiped on container restart.

| File | Deleted when |
|---|---|
| `{uuid}.png` | Immediately after Slack upload |
| `{uuid}.html` | 10 minutes after posting (keeps interactive URL alive briefly) |
| `{uuid}.html` (no APP_URL) | Immediately — HTML won't be served so no reason to keep it |

Once the PNG is uploaded to Slack it is permanent in the Slack workspace regardless of server state.

---

## Interactive URL

If `APP_URL` env var is set (Railway public URL), the bot posts a second message:
```
<https://your-app.railway.app/charts/{chart_id}|Open interactive chart>
```
This serves `{uuid}.html` via `GET /charts/{chart_id}` in `main.py`. The interactive chart supports hover tooltips, zoom, and pan via Plotly.

---

## Future: Dedicated `chart_plotly` package

For a fully standalone interactive chart package (separate from this project), extract `chart_png/` into `chart_plotly/`:
- `store.py` → HTML-only output, no PNG, no kaleido
- `tool.py` → returns `chart_url` instead of `chart_path`
- Remove `kaleido` from dependencies

`bot/tools.py`, `bot/agent.py`, and `bot/slack_handler.py` need minimal changes to handle a URL instead of a file path.

---

## Dependencies

- `plotly==5.22.0` — figure building and PNG export
- `kaleido==0.2.1` — headless rendering engine used by `fig.write_image()`
