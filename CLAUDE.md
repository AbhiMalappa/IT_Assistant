# CLAUDE.md — IT Incident Bot

This file contains the full architecture, decisions, and instructions for building the IT Incident Bot. Read this entire file before writing any code.

---

## Project Overview

An AI-powered IT incident management chatbot deployed on **Slack**. It helps incident managers search past incidents, diagnose issues, suggest resolutions, log new incidents, analyze patterns, and answer data analysis questions — all via natural language in Slack.

---

## Final Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Only language used — no Node.js |
| Slack Integration | `slack-bolt` (Python) | Event-driven, socket mode for dev |
| AI / Reasoning | Anthropic Claude (`claude-sonnet-4-20250514`) | Core reasoning engine |
| Embeddings | OpenAI (`text-embedding-3-large`) | Switchable to Voyage AI — see abstraction below |
| Vector Store | Pinecone | Switchable — see abstraction below |
| Relational DB | Supabase (pure Postgres) | No pgvector — Pinecone handles all vectors |
| Agent Pattern | Agentic tool-use (no LangChain) | Claude decides at runtime which tool to call — RAG, SQL, or direct lookup |
| Backend Server | FastAPI | Handles Slack event webhooks |
| Deployment | Railway | Single service deployment |

---

## Project Structure

```
IT_Assistant/
├── main.py                            # FastAPI app entry point + Slack socket mode startup
├── bot/
│   ├── slack_handler.py               # Slack Bolt event handling (messages, slash commands)
│   ├── agent.py                       # Agentic loop: tool definitions, system prompt, Claude tool-use
│   ├── tools.py                       # Tool implementations: search_incidents, sql_query, get_all_by_system, get_incident_by_number
│   ├── conversation_manager.py        # [planned] Token-aware buffer memory, summarisation, tool tracking
│   ├── claude_client.py               # Anthropic client singleton + model name
│   └── rag_pipeline.py                # [reference] Original RAG logic — superseded by agent.py + tools.py
├── embeddings/
│   ├── base.py                        # Abstract base class for embedding providers
│   ├── openai_embedder.py             # OpenAI text-embedding-3-large implementation
│   └── voyage_embedder.py             # Voyage AI implementation (ready to switch to)
├── vectorstore/
│   ├── base.py                        # Abstract base class for vector store providers
│   └── pinecone_store.py              # Pinecone implementation with namespace support
├── db/
│   ├── supabase_client.py             # Supabase client singleton
│   ├── incidents.py                   # CRUD operations for incidents table
│   └── conversation_messages.py       # [planned] CRUD for conversation_messages table
├── anomaly_detection/
│   ├── __init__.py
│   ├── analyser.py                    # Pre-flight checks, granularity/trend/seasonality detection, method options
│   ├── threshold.py                   # Auto-suggest Z-score threshold (3–9) based on noise level (CV)
│   ├── detector.py                    # IQR capping + STL/MSTL/rolling Z-score + anomaly flagging
│   └── tool.py                        # analyse_for_anomalies() + run_anomaly_detection() wrappers
├── chart_png/
│   ├── __init__.py
│   ├── generator.py                   # Builds Plotly Figure from data + chart config (no project knowledge)
│   ├── store.py                       # Saves Figure as PNG to /tmp/charts/
│   └── tool.py                        # plot_chart() tool: calls generator + store, returns chart_path
├── scripts/
│   ├── load_incidents.py              # One-time CSV loader — already run
│   └── re_embed.py                    # Re-embed all incidents when switching providers
├── migrations/
│   └── schema.sql                     # Full Supabase schema (incidents + conversation_messages + time_series_metrics)
├── docs/
│   └── file_reference.md             # Plain English guide to every file
├── Inputs/
│   └── IT_Incidents_v1.csv           # Source incident data (510 records, already loaded)
├── .env.example                       # All required environment variables
├── requirements.txt                   # All Python dependencies
├── Dockerfile                         # For Railway deployment
├── railway.toml                       # Railway configuration
└── README.md                          # Setup guide
```

---

## Architecture Overview

```
User (Slack)
     ↓
Slack Bolt (slack_handler.py)
     ↓
Agent (agent.py)  ←── Claude decides which tool(s) to call at runtime
     ├── search_incidents()        → Pinecone (semantic search, top-k)
     │                             → Supabase (fetch full records)
     ├── get_incident_by_number()  → Supabase (exact INC lookup)
     ├── sql_query()               → Supabase (aggregation, counts, ranking)
     ├── get_all_by_system()       → Supabase (all incidents for a system)
     ├── forecast_incidents()      → Supabase + ExponentialSmoothingForecaster
     ├── analyse_for_anomalies()   → anomaly_detection/analyser.py (presents method options)
     ├── run_anomaly_detection()   → anomaly_detection/detector.py (STL/MSTL/rolling Z-score)
     └── plot_chart()              → chart_png → /tmp/charts/*.png
          ↓
     Claude formulates final answer
          ↓
     agent.run() returns (text, chart_path)
          ↓
     slack_handler: posts text + uploads PNG via files_upload_v2
          ↓
     Text + chart appear inline in Slack
```

### Why Agentic Tool-Use
Pure RAG (top-k) is insufficient for aggregation questions like "top printer issues" —
it only retrieves the k most similar vectors, missing the full dataset needed for ranking.
Claude uses tool-use to decide at runtime whether to do semantic search, SQL aggregation,
or a full system lookup — or a combination of these.

---

## Core Design Principles

### 1. Embedding Provider Abstraction

Never call OpenAI or Voyage directly in business logic. Always go through the abstract interface.

```python
# embeddings/base.py
from abc import ABC, abstractmethod
from typing import List

class BaseEmbedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> List[float]:
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass
```

```python
# embeddings/openai_embedder.py
from openai import OpenAI
from .base import BaseEmbedder

class OpenAIEmbedder(BaseEmbedder):
    MODEL = "text-embedding-3-large"

    def __init__(self):
        self.client = OpenAI()

    def embed(self, text: str) -> List[float]:
        response = self.client.embeddings.create(model=self.MODEL, input=text)
        return response.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        response = self.client.embeddings.create(model=self.MODEL, input=texts)
        return [d.embedding for d in response.data]
```

```python
# embeddings/voyage_embedder.py
# Voyage AI implementation — ready to use when switching
import voyageai
from .base import BaseEmbedder

class VoyageEmbedder(BaseEmbedder):
    MODEL = "voyage-large-2"

    def __init__(self):
        self.client = voyageai.Client()

    def embed(self, text: str) -> List[float]:
        result = self.client.embed([text], model=self.MODEL)
        return result.embeddings[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        result = self.client.embed(texts, model=self.MODEL)
        return result.embeddings
```

**Switching providers:**
1. Change `EMBEDDING_PROVIDER=openai` to `EMBEDDING_PROVIDER=voyage` in `.env`
2. Run `python scripts/re_embed.py` to re-embed all existing data
3. Done — no other code changes needed

---

### 2. Vector Store Abstraction

Same pattern as embeddings — never call Pinecone directly in business logic.

```python
# vectorstore/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseVectorStore(ABC):
    @abstractmethod
    def upsert(self, id: str, vector: List[float], metadata: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def search(self, query_vector: List[float], top_k: int, filters: Dict = None) -> List[Dict]:
        pass

    @abstractmethod
    def delete(self, id: str) -> None:
        pass
```

```python
# vectorstore/pinecone_store.py
from pinecone import Pinecone
from .base import BaseVectorStore

class PineconeStore(BaseVectorStore):
    def __init__(self, api_key: str, index_name: str):
        pc = Pinecone(api_key=api_key)
        self.index = pc.Index(index_name)

    def upsert(self, id: str, vector: List[float], metadata: Dict[str, Any]) -> None:
        self.index.upsert(vectors=[{"id": id, "values": vector, "metadata": metadata}])

    def search(self, query_vector: List[float], top_k: int = 5, filters: Dict = None) -> List[Dict]:
        results = self.index.query(vector=query_vector, top_k=top_k, filter=filters, include_metadata=True)
        return results.matches

    def delete(self, id: str) -> None:
        self.index.delete(ids=[id])
```

---

### 3. Agentic Tool-Use Pipeline

Claude decides at runtime which tool(s) to call. The agentic loop in `bot/agent.py`:

```
1. User message → Claude (with 4 tool definitions)
2. Claude returns tool_use block (tool name + inputs)
3. We execute the tool via TOOL_REGISTRY in bot/tools.py
4. Result returned to Claude as tool_result
5. Claude may call another tool or return final answer
6. Loop until stop_reason == "end_turn"
```

Tools available to Claude:
- `search_incidents(query, top_k, filters)` — semantic search via Pinecone → Supabase
- `get_incident_by_number(number)` — exact INC lookup from Supabase
- `get_all_by_system(system, limit)` — full dataset for a system from Supabase
- `sql_query(query)` — safe SELECT SQL on Supabase via psycopg2 (aggregation/ranking)

`bot/rag_pipeline.py` is kept for reference only — its logic is absorbed into `bot/tools.py`.

---

## Database Schema (Supabase / Postgres)

```sql
-- migrations/schema.sql
-- Schema based on IT_Incidents_v1.csv source data

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    number VARCHAR(20) UNIQUE NOT NULL,       -- e.g., INC17089043
    opened_at TIMESTAMPTZ,
    opened_by TEXT,
    state TEXT CHECK (state IN ('Open', 'Closed', 'In Progress', 'Cancelled', 'On hold')),
    contact_type TEXT,                        -- Alert, Phone, Self Service, Direct Input, Web Services
    assignment_group TEXT,                    -- printer_support, SAP_support, network_support, etc.
    assigned_to TEXT,
    priority VARCHAR(10) CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    configuration_item TEXT,                  -- Printer, SAP, Workstation, Server, etc.
    resolution_tier TEXT,                     -- Solved - Hardware Related / Application related / Others
    short_description TEXT,
    caller TEXT,
    label TEXT,                               -- Root cause category (SAP Server Down, Defective Hardware, etc.)
    resolution_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER incidents_updated_at BEFORE UPDATE ON incidents
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE time_series_metrics (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric      TEXT NOT NULL,          -- e.g. store_order_count, api_traffic
    timestamp   TIMESTAMPTZ NOT NULL,
    value       NUMERIC NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (metric, timestamp)
);

CREATE INDEX idx_metrics_metric_ts ON time_series_metrics(metric, timestamp);

-- NOTE: changes and incident_changes tables to be added later when change request data is available.
```

---

## Pinecone Setup

- **Index name:** `it-assistant`
- **Dimensions:** `3072` (for `text-embedding-3-large`) — change to `1024` if switching to Voyage `voyage-large-2`
- **Metric:** `cosine`
- **Metadata stored per vector:**
  - `source_type` — always `"incident"` (future: `"change"`, `"document"`, `"transcript"`)
  - `source_id` — UUID linking back to Supabase `incidents.id`
  - `title` — `short_description` for quick display
  - `created_at` — ISO timestamp string (maps to `opened_at`)
  - `number` — INC number for quick display (e.g., INC17089043)
  - `priority` — for filtered search (Low, Medium, High, Critical)
  - `state` — for filtered search (Open, Closed, In Progress, Cancelled, On hold)
  - `assignment_group` — for filtered search
  - `configuration_item` — for filtered search
  - `label` — root cause category for filtered search
  - `opened_at` — ISO timestamp string
- **Namespace:** `incidents` — all incident vectors live here; future sources get their own namespace

---

## Claude System Prompt

Lives in `bot/agent.py` as `SYSTEM_PROMPT`. Key sections:

- **Identity** — IT Assistant bot for incident managers
- **Developer/Support** — Abhiraj Malappa, abhiraj7m@gmail.com
- **Tool guidance** — when to use each of the 4 tools
- **Incidents table schema** — column names and valid values so Claude generates correct SQL
- **Response rules** — concise, bullet points, always cite INC numbers, end with References line
- **Conversational** — handle greetings, guide users, surface support contact when needed

---

## Slack Bot Capabilities

### Slash Commands
| Command | Description |
|---|---|
| `/incident search <query>` | Semantic search over past incidents |
| `/incident log` | Start logging a new incident (interactive) |
| `/incident status <id>` | Get current status of an incident |
| `/incident summary <id>` | Get a plain English summary of an incident |

### Natural Language (via @mention or DM)
- "What caused the last 3 P1 outages?"
- "Find incidents related to the payment gateway"
- "How many incidents did we have last month?"
- "What's the average resolution time for database issues?"
- "Are there any changes scheduled that could be causing this?"
- "Summarize incident INC-1234"

---

## Environment Variables

```bash
# .env.example

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key

# OpenAI (embeddings)
OPENAI_API_KEY=your_openai_api_key

# Voyage AI (optional — for switching)
VOYAGE_API_KEY=your_voyage_api_key

# Embedding provider — "openai" or "voyage"
EMBEDDING_PROVIDER=openai

# Pinecone
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=it-assistant

# Supabase
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_KEY=your_supabase_service_role_key
DATABASE_URL=postgresql://postgres:[password]@[host]:5432/postgres

# Slack
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_SIGNING_SECRET=your_slack_signing_secret
SLACK_APP_TOKEN=xapp-your-app-level-token  # for socket mode in dev

# App
PORT=8000
ENVIRONMENT=development  # "development" or "production"
```

---

## requirements.txt

```
fastapi==0.111.0
uvicorn==0.30.0
slack-bolt==1.18.1
anthropic==0.28.0
openai==1.35.0
voyageai==0.2.3
pinecone-client==4.1.0
supabase==2.5.0
psycopg2-binary==2.9.9
python-dotenv==1.0.1
pydantic==2.7.4
httpx==0.27.0
```

---

## Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## railway.toml

```toml
[build]
builder = "dockerfile"

[deploy]
startCommand = "uvicorn main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

---

## Re-embedding Script

Run when switching embedding providers. See actual implementation in `scripts/re_embed.py`.

Key details:
- Fetches all incidents via `db.incidents.get_all()`
- Embeds text combining: `number + short_description + label + configuration_item + assignment_group + resolution_notes`
- Upserts to Pinecone namespace `incidents` with universal metadata (`source_type`, `source_id`, `title`, `created_at`) plus incident-specific fields
- Usage: `python scripts/re_embed.py`

---

## Key Decisions Log

| Decision | Choice | Reason |
|---|---|---|
| Language | Python | Developer familiarity |
| Framework | No LangChain | Full control, easier to debug, custom incident logic |
| Embeddings | OpenAI (switchable) | Mature SDK, abstraction layer allows future switch to Voyage |
| Vector DB | Pinecone | Decoupled from relational DB, portable, purpose-built, namespace support |
| Relational DB | Supabase (Postgres) | Simple managed Postgres, no pgvector needed |
| Deployment | Railway | Zero DevOps, small team, fast iteration |
| Charting | Plotly PNG via `chart_png/` | Inline in Slack, no server dependency, ephemeral /tmp storage |
| Anomaly Detection | STL/MSTL/rolling Z-score via `anomaly_detection/` | Two-step flow: analyse → user picks method → run. IQR capping, auto threshold (3–9) |
| Agent Pattern | Claude tool-use | Claude decides RAG vs SQL vs direct lookup at runtime — no hardcoded intent classifier |
| Aggregation | Text-to-SQL via psycopg2 | Pure RAG misses full dataset; SQL handles counts, rankings, trends correctly |
| Conversation Memory | Supabase (swappable) | Token-aware buffer, dual storage (full + summary), tool tracking per message |
| Pinecone Namespaces | incidents / changes / documents / transcripts | Single index, partitioned by source type — no index changes needed when adding new sources |

---

## Build Order

Build in this sequence:

1. `migrations/schema.sql` — Supabase schema (incidents + conversation_messages + time_series_metrics)
2. `db/supabase_client.py` + `db/incidents.py` — DB layer
3. `embeddings/base.py` + `embeddings/openai_embedder.py` + `embeddings/voyage_embedder.py`
4. `vectorstore/base.py` + `vectorstore/pinecone_store.py`
5. `bot/claude_client.py` — Anthropic client singleton
6. `bot/tools.py` — tool implementations (search_incidents, sql_query, get_all_by_system, get_incident_by_number)
7. `bot/agent.py` — tool definitions + agentic loop + system prompt
8. `bot/conversation_manager.py` — [planned] token-aware memory + summarisation
9. `db/conversation_messages.py` — [planned] CRUD for conversation_messages table
10. `bot/slack_handler.py` — Slack events and slash commands
11. `main.py` — FastAPI entry point
12. `scripts/re_embed.py` — utility script
13. `Dockerfile` + `railway.toml` + `.env.example` + `requirements.txt`
14. `README.md` — setup instructions

---

## Conversation Memory Architecture

### Design Goals
- Maintain context across a Slack conversation thread
- Stay within Claude's context window budget
- Preserve full history for audit without bloating the prompt
- Storage layer is swappable (Supabase now → Redis/Upstash later)

---

### Buffer Memory

- **Window:** Last 10 turns (20 messages: 10 user + 10 assistant)
- **Token budget:** Max 4000 tokens for history injected into Claude's context
- **Retrieval order:** Start from most recent message, work backwards, stop when token budget is exceeded
- Token count is stored per message at write time — no re-counting on retrieval

---

### Storage: Supabase

Add to `migrations/schema.sql`:

```sql
CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id       TEXT NOT NULL,
    role            VARCHAR(10) NOT NULL,
    full_content    TEXT,
    summary         TEXT,
    use_summary     BOOLEAN DEFAULT FALSE,
    tool_used       TEXT,
    tool_input      JSONB,
    tool_result     TEXT,
    sql_query       TEXT,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_thread_id_created ON conversation_messages(thread_id, created_at DESC);
```

---

### Summarisation

Store **both** `full_content` and `summary` for every message.

Trigger summarisation (`use_summary = TRUE`) when any of these are true:
- `tool_used = 'sql_query'` — SQL results can be verbose
- `tool_used = 'get_all_by_system'` — returns up to 100 records
- Response token count exceeds 300 tokens

When `use_summary = TRUE`:
- Send `summary` to Claude in the buffer (not `full_content`)
- `full_content` is always preserved in Supabase for audit — never discarded

---

### Tool Tracking (per message)

Every message row stores:

| Column | Description |
|---|---|
| `tool_used` | Name of the tool Claude called (e.g., `sql_query`, `search_incidents`) |
| `tool_input` | Parameters Claude passed to the tool, stored as JSONB |
| `tool_result` | Raw result returned by the tool |
| `sql_query` | Actual SQL string — only populated when `tool_used = 'sql_query'` |

---

### ConversationManager Class

File: `bot/conversation_manager.py`

Design principles:
- **Storage-agnostic** — abstract base class, Supabase is the first implementation
- Swappable to Redis or Upstash later by implementing the same interface
- Handles: write message, retrieve buffer, trigger summarisation, count tokens

```python
# bot/conversation_manager.py (interface)

class BaseConversationManager(ABC):
    @abstractmethod
    def save_message(self, thread_id, role, content, **kwargs) -> None:
        """Persist a message with optional tool tracking fields."""
        pass

    @abstractmethod
    def get_buffer(self, thread_id) -> List[Dict]:
        """Return token-aware message buffer for Claude context injection."""
        pass

    @abstractmethod
    def should_summarise(self, tool_used: str, token_count: int) -> bool:
        """Return True if this message's content should be summarised."""
        pass
```

Summarisation trigger logic in `should_summarise()`:
```python
SUMMARISE_TOOLS = {"sql_query", "get_all_by_system"}
TOKEN_THRESHOLD = 300

def should_summarise(self, tool_used: str, token_count: int) -> bool:
    return tool_used in SUMMARISE_TOOLS or token_count > TOKEN_THRESHOLD
```

---

### Thread ID Strategy (Slack)

- For **DMs:** use Slack `channel` ID (each DM is a unique channel per user)
- For **channel mentions:** use Slack `thread_ts` if in a thread, otherwise `channel + ts`
- Thread ID will be passed into `agent.run(user_message, thread_id)` when memory is implemented — current signature is `run(user_message: str)` only

---

## Data Analysis / Aggregation

Handled by the `sql_query` tool inside the agentic loop. Claude generates a safe SELECT query, we execute it on Supabase via psycopg2, and results are returned to Claude to format the answer. No separate intent classifier needed — Claude decides at runtime.

Requires `DATABASE_URL` env var (Supabase connection string).

---

## README Must Include

- Prerequisites (Python 3.11+, Pinecone account, Supabase account, Slack App setup)
- Step-by-step Slack App creation (Bot Token Scopes, Event Subscriptions, Socket Mode)
- How to run `migrations/schema.sql` in Supabase
- How to create Pinecone index with correct dimensions
- How to set all environment variables
- How to run locally: `uvicorn main:app --reload`
- How to deploy to Railway (connect GitHub repo, set env vars)
- How to switch embedding providers (change `.env` + run `re_embed.py`)
