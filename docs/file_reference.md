# IT Assistant — File Reference

This document explains what each file in the project does, in plain English.

---

## db/

### `db/conversation_messages.py` *(planned)*
CRUD operations for the `conversation_messages` table. Supports writing messages (with tool tracking fields), fetching the last N messages by thread, and token-aware buffer retrieval. Used by `ConversationManager`.

### `db/supabase_client.py`
Sets up the Supabase connection. Creates the client once using the URL and service key from environment variables, and exports it for the rest of the app to import. No other file connects to Supabase directly — they all import from here.

### `db/incidents.py`
All database operations for the `incidents` table. Functions:
- `get_by_ids(ids)` — fetch full incident records by UUID list. Used by the RAG pipeline after Pinecone returns vector search matches.
- `get_all()` — fetch all incidents. Used by the re-embed script when switching embedding providers.
- `insert(incident)` — log a new incident. Called when a user asks the bot to log an incident from Slack.
- `update(id, fields)` — update an incident's fields (status, resolution notes, etc.).
- `get_by_number(number)` — look up a specific incident by its INC number (e.g., INC17089043).

### `db/__init__.py`
Empty file that makes the `db/` folder a Python package. Required so other files can import from it using `from db.incidents import ...` or `from db.supabase_client import ...`. Without it, Python won't recognize `db/` as a package. The same pattern applies to `embeddings/`, `vectorstore/`, and `bot/` folders.

---

## embeddings/

### `embeddings/base.py`
Abstract base class that defines the interface all embedding providers must follow. Contains two methods: `embed(text)` and `embed_batch(texts)`. Business logic never calls OpenAI or Voyage directly — it always goes through this interface.

### `embeddings/openai_embedder.py`
OpenAI implementation of the embedder. Uses `text-embedding-3-large` (3072 dimensions). This is the default provider.

### `embeddings/voyage_embedder.py`
Voyage AI implementation of the embedder. Uses `voyage-large-2` (1024 dimensions). Ready to use — just change `EMBEDDING_PROVIDER=voyage` in `.env` and run the re-embed script.

---

## vectorstore/

### `vectorstore/base.py`
Abstract base class for vector store providers. Defines three methods: `upsert()`, `search()`, and `delete()`. Business logic never calls Pinecone directly.

### `vectorstore/pinecone_store.py`
Pinecone implementation of the vector store. Handles upserting incident vectors, searching by similarity, and deleting vectors. Index name and API key come from environment variables.

---

## bot/

### `bot/claude_client.py`
Holds the Anthropic client singleton and model name. The system prompt and agentic logic have moved to `bot/agent.py`.

### `bot/agent.py`
The brain of the bot. Contains:
- Full system prompt (bot purpose, tool guidance, response rules, developer/support contact)
- Tool definitions in Claude's JSON schema format (7 tools: search, lookup, system fetch, SQL, forecast, anomaly detection, chart)
- Hybrid model strategy: Haiku by default (cheap/fast), upgrades to Sonnet mid-loop when `forecast_incidents` or `run_anomaly_detection` is called
- SQL result cap: 100 rows returned to Claude; full dataset injected into `plot_chart` and anomaly detection tools
- Agentic loop: sends user message to Claude → Claude picks a tool → we execute it → feed result back → repeat until Claude gives a final answer
- `run()` returns a 3-tuple: `(text_response, chart_path, chart_id)` — chart fields are `None` if no chart was generated

### `bot/tools.py`
All tool implementations that Claude can call at runtime:
- `search_incidents(query, top_k, filters)` — semantic search via Pinecone + Supabase fetch
- `get_incident_by_number(number)` — exact lookup by INC number (e.g., INC17089320)
- `get_all_by_system(system, limit)` — fetch all incidents for a system (bypasses top-k limit)
- `sql_query(query)` — execute a safe SELECT SQL on Supabase for aggregation and ranking. Allowed tables: `incidents`, `time_series_metrics`
- `forecast_incidents(periods, group_by, filters)` — forecast future incident volume using Exponential Smoothing
- `plot_chart(data, chart_type, x_column, y_column, ...)` — generate a Plotly PNG chart, delegates to `chart_png/`
- `run_anomaly_detection(series_data, period_column, value_column, method)` — run detection with auto method selection, delegates to `anomaly_detection/`
- `analyse_for_anomalies` — kept in TOOL_REGISTRY but excluded from TOOL_DEFINITIONS (commented out). Re-enable for interactive two-step method selection flow.
- `TOOL_REGISTRY` — dictionary mapping tool names to functions, used by the agent dispatcher

### `bot/rag_pipeline.py`
Kept for reference. Original RAG logic (embed → Pinecone → Supabase → Claude). Core functionality absorbed into `bot/tools.py` and `bot/agent.py`.

### `bot/conversation_manager.py`
Manages per-thread conversation memory. Abstract base class (storage-agnostic) with a Supabase implementation. Handles:
- Writing messages with tool tracking fields (tool_used, tool_input, tool_result, sql_query)
- Token-aware buffer retrieval (last 5 turns / 10 messages, max 2000 tokens, most recent first)
- Tiered truncation (no extra API call): sql_query/get_all_by_system → 300 tokens, forecast/anomaly → 500 tokens, others stored in full
- Dual storage: `full_content` always saved, truncated `summary` sent to Claude when response exceeds limit
- `reset(thread_id)` — deletes all conversation history for a thread (used by `/incident reset`)

### `bot/slack_handler.py`
Handles Slack events and slash commands using `slack-bolt`. Listens for mentions, DMs, and `/incident` commands. Calls `agent.run()`, posts the text response, and if a chart was generated: uploads the PNG inline and posts an interactive URL link. Cleans up `/tmp` chart files after upload. Slash commands: `search`, `status`, `summary`, `reset`, `help`.

---

## anomaly_detection/

Standalone internal package for time series anomaly detection. Zero knowledge of incidents, Slack, or this project — accepts any numeric pandas Series. Reusable in other projects.

### `anomaly_detection/analyser.py`
Inspects a time series before running detection. Performs pre-flight checks (hard stops + warnings), infers granularity from index labels, detects trend (linear regression) and seasonality (ACF), and builds a ranked list of viable method options with a recommended pick.

### `anomaly_detection/threshold.py`
Auto-selects a Z-score threshold in the range 3.0–9.0 based on the Coefficient of Variation (CV) of residuals. Low noise → tight threshold (3.0). Very noisy data → loose threshold (9.0) to reduce false positives.

### `anomaly_detection/detector.py`
Runs anomaly detection. Caps extreme outliers via IQR before model fitting (originals used for scoring), fits STL/MSTL/rolling Z-score decomposition, computes Z-scores on residuals, and returns flagged anomalies with actual value, expected value, Z-score, and direction (spike/drop).

### `anomaly_detection/tool.py`
Two thin wrappers registered in `TOOL_REGISTRY` for Claude:
- `analyse_for_anomalies(series_data, period_column, value_column)` — returns characteristics + method options
- `run_anomaly_detection(series_data, period_column, value_column, method)` — runs detection, returns flagged anomalies

---

## chart_png/

Standalone internal package for generating PNG charts. Has zero knowledge of incidents, Slack, or this project — it accepts generic tabular data and chart configuration. Reusable in other projects.

### `chart_png/generator.py`
Builds a Plotly `Figure` object from data and chart configuration. Supports four chart types: `bar`, `horizontal_bar`, `line`, and `forecast` (historical bars + forecast line overlay). No file I/O — returns a figure object only.

### `chart_png/store.py`
Saves a Plotly figure to `/tmp/charts/` as both PNG (`kaleido`) and self-contained HTML (`fig.to_html`). Returns the PNG file path and a UUID chart ID. The UUID is shared between both files.

### `chart_png/tool.py`
Thin wrapper called by Claude via the agentic loop. Calls `generator.py` and `store.py`, returns `{"chart_path": ..., "chart_id": ..., "chart_title": ...}`. This is what gets registered in `TOOL_REGISTRY`.

---

## scripts/

### `scripts/load_incidents.py`
One-time data loading script. Reads `Inputs/IT_Incidents_v1.csv` and inserts all 510 incidents into the Supabase `incidents` table. Already run — no need to run again unless re-loading fresh data.

### `scripts/re_embed.py`
Run this when switching embedding providers (OpenAI → Voyage or vice versa). Fetches all incidents from Supabase, re-embeds them using the new provider, and upserts the new vectors into Pinecone.

### `scripts/load_metrics.py`
One-time data loading script. Reads `Inputs/store_order_count.csv` and `Inputs/api_traffic.csv` and inserts all records into the Supabase `time_series_metrics` table. Already run — no need to run again unless re-loading fresh data.

### `scripts/check_anthropic.py`
Quick connectivity check. Sends a minimal API call to verify the Anthropic API key is valid and has credit. Run with `python scripts/check_anthropic.py`.

---

## Root files

### `main.py`
FastAPI app entry point. Starts the web server and launches the Slack socket mode handler in a background thread. Also serves interactive Plotly charts via `GET /charts/{chart_id}` — reads the HTML file from `/tmp/charts/` and returns it as an HTML response.

### `.env` / `.env.example`
Environment variables: API keys for Anthropic, OpenAI, Pinecone, Supabase, and Slack. Never commit `.env` to version control.

### `requirements.txt`
All Python dependencies. Install with `pip install -r requirements.txt`.

### `Dockerfile`
Container definition for deployment. Uses the full `python:3.11` image (not slim) — required because `kaleido` needs system libraries to render Plotly figures to PNG.

### `railway.toml`
Railway deployment configuration. Tells Railway to use the Dockerfile and restart on failure.

---

## Data

### `Inputs/IT_Incidents_v1.csv`
Source data file. Contains 510 IT incident records. Already loaded into Supabase. One duplicate INC number was renamed to `INC-DUP-00001` during load.

### `Inputs/store_order_count.csv`
15-minute store order count metrics. 2,869 rows covering Feb–Mar 2026. Already loaded into `time_series_metrics` (metric = `store_order_count`).

### `Inputs/api_traffic.csv`
15-minute API traffic metrics. 2,874 rows covering Feb–Mar 2026. Already loaded into `time_series_metrics` (metric = `api_traffic`).
