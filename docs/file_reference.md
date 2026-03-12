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
- Tool definitions in Claude's JSON schema format (what each tool does and when to use it)
- Agentic loop: sends user message to Claude → Claude picks a tool → we execute it → feed result back → repeat until Claude gives a final answer

### `bot/tools.py`
All tool implementations that Claude can call at runtime:
- `search_incidents(query, top_k, filters)` — semantic search via Pinecone + Supabase fetch
- `get_incident_by_number(number)` — exact lookup by INC number (e.g., INC17089320)
- `get_all_by_system(system, limit)` — fetch all incidents for a system (bypasses top-k limit)
- `sql_query(query)` — execute a safe SELECT SQL on Supabase for aggregation and ranking
- `TOOL_REGISTRY` — dictionary mapping tool names to functions, used by the agent dispatcher

### `bot/rag_pipeline.py`
Kept for reference. Original RAG logic (embed → Pinecone → Supabase → Claude). Core functionality absorbed into `bot/tools.py` and `bot/agent.py`.

### `bot/conversation_manager.py` *(planned)*
Manages per-thread conversation memory. Abstract base class (storage-agnostic) with a Supabase implementation. Handles:
- Writing messages with tool tracking fields (tool_used, tool_input, tool_result, sql_query)
- Token-aware buffer retrieval (last 10 turns, max 4000 tokens, most recent first)
- Summarisation trigger logic (auto-summarise sql_query/get_all_by_system responses and responses over 300 tokens)
- Dual storage: `full_content` always saved, `summary` sent to Claude when `use_summary = TRUE`

### `bot/slack_handler.py`
Handles Slack events and slash commands using `slack-bolt`. Listens for mentions, DMs, and `/incident` commands. Calls `agent.run()` and sends responses back to Slack.

---

## scripts/

### `scripts/load_incidents.py`
One-time data loading script. Reads `Inputs/IT_Incidents_v1.csv` and inserts all 510 incidents into the Supabase `incidents` table. Already run — no need to run again unless re-loading fresh data.

### `scripts/re_embed.py`
Run this when switching embedding providers (OpenAI → Voyage or vice versa). Fetches all incidents from Supabase, re-embeds them using the new provider, and upserts the new vectors into Pinecone.

---

## Root files

### `main.py`
FastAPI app entry point. Starts the web server and registers the Slack Bolt app as a handler for incoming webhook events.

### `.env` / `.env.example`
Environment variables: API keys for Anthropic, OpenAI, Pinecone, Supabase, and Slack. Never commit `.env` to version control.

### `requirements.txt`
All Python dependencies. Install with `pip install -r requirements.txt`.

### `Dockerfile`
Container definition for deployment. Uses Python 3.11 slim image.

### `railway.toml`
Railway deployment configuration. Tells Railway to use the Dockerfile and restart on failure.

---

## Data

### `Inputs/IT_Incidents_v1.csv`
Source data file. Contains 510 IT incident records. Already loaded into Supabase. One duplicate INC number was renamed to `INC-DUP-00001` during load.
